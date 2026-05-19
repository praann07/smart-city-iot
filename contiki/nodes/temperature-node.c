#include "contiki.h"
#include "net/ipv6/simple-udp.h"
#include "sys/log.h"
#include "sys/etimer.h"
#include "lib/random.h"
#include "net/routing/routing.h"
#include "net/routing/rpl-lite/rpl.h"
#include "net/linkaddr.h"
#include "sys/energest.h"
#include <stdio.h>
#include <string.h>

#define LOG_MODULE "TEMP"
#define LOG_LEVEL  LOG_LEVEL_INFO

#define UDP_PORT  8765
#define CMD_PORT  8766
#define SEND_INTERVAL (15 * CLOCK_SECOND)

static struct simple_udp_connection udp_conn;
static struct simple_udp_connection cmd_conn;
static uint16_t battery_mv    = 3000;
static uint32_t seqno         = 0;
static clock_time_t send_interval = SEND_INTERVAL;

/*
 * Diurnal temperature model (linear ramp approximation of sine curve).
 * Simulation starts at virtual 06:00.
 *   06:00 -> 14:00 : ramp up 18 C -> 26 C (8 h * +1 C/h)
 *   14:00 -> 22:00 : ramp down 26 C -> 18 C
 * Returns temperature in tenths of a degree Celsius.
 */
static int16_t sample_celsius_tenths(void)
{
  uint32_t sim_sec = (uint32_t)clock_seconds();
  uint32_t vhour   = (6 + sim_sec / 3600) % 24;
  int16_t base_tenths;
  if(vhour < 14)
    base_tenths = 180 + (int16_t)((vhour > 6 ? vhour - 6 : 0) * 10);
  else
    base_tenths = 260 - (int16_t)((vhour - 14) * 10);
  /* clamp to [180, 260] */
  if(base_tenths < 180) base_tenths = 180;
  if(base_tenths > 260) base_tenths = 260;
  int16_t jitter = (int16_t)(random_rand() % 21) - 10; /* ±1.0 C */
  return base_tenths + jitter;
}

/*
 * Battery drain tied to RPL rank.
 * Temperature nodes sleep longer (15s vs 10s) so base drain is smaller.
 */
static uint16_t sample_battery_mv(uint16_t rank)
{
  uint16_t hop   = rank / 256;
  uint16_t r     = random_rand() % 100;
  uint16_t drain = 0;
  if(r < 30) {
    drain = 0;
  } else if(r < 80) {
    drain = 1 + hop;                   /* normal TX, slower cadence   */
  } else {
    drain = 2 + hop * 2;               /* burst / retransmission      */
  }
  if(battery_mv > drain) battery_mv -= drain; else battery_mv = 0;
  return battery_mv;
}

static void get_energest(uint32_t *cpu_ms, uint32_t *lpm_ms,
                         uint32_t *tx_ms,  uint32_t *rx_ms)
{
  energest_flush();
#define E2MS(t) ((uint32_t)((t) * 1000UL / RTIMER_SECOND))
  *cpu_ms = E2MS(energest_type_time(ENERGEST_TYPE_CPU));
  *lpm_ms = E2MS(energest_type_time(ENERGEST_TYPE_LPM));
  *tx_ms  = E2MS(energest_type_time(ENERGEST_TYPE_TRANSMIT));
  *rx_ms  = E2MS(energest_type_time(ENERGEST_TYPE_LISTEN));
#undef E2MS
}

static void get_parent_info(char *parent_buf, size_t parent_len,
                            uint16_t *rank_out)
{
  *rank_out = curr_instance.dag.rank;
  rpl_nbr_t *pref = curr_instance.dag.preferred_parent;
  if(pref != NULL) {
    const uip_ipaddr_t *pip = rpl_neighbor_get_ipaddr(pref);
    if(pip != NULL) {
      snprintf(parent_buf, parent_len, "%02x%02x",
               pip->u8[14], pip->u8[15]);
      return;
    }
  }
  snprintf(parent_buf, parent_len, "none");
}

/*
 * Downlink command receiver.
 * Expects JSON: {"duty_cycle":<1-100>}
 */
static void cmd_rx(struct simple_udp_connection *c,
                   const uip_ipaddr_t *sender,
                   uint16_t sender_port,
                   const uip_ipaddr_t *receiver,
                   uint16_t receiver_port,
                   const uint8_t *data, uint16_t datalen)
{
  const char *p   = (const char *)data;
  const char *key = strstr(p, "\"duty_cycle\"");
  if(!key) return;
  const char *col = strchr(key, ':');
  if(!col) return;
  int dc = 0, i = 1;
  while(col[i] && (col[i] < '0' || col[i] > '9')) i++;
  while(col[i] >= '0' && col[i] <= '9') dc = dc * 10 + (col[i++] - '0');
  if(dc > 0 && dc <= 100) {
    send_interval = (clock_time_t)((100 / dc) * SEND_INTERVAL);
    LOG_INFO("CMD duty_cycle=%d%% new_interval=%lu ticks\n",
             dc, (unsigned long)send_interval);
  }
}

PROCESS(temperature_node_process, "Temperature node");
AUTOSTART_PROCESSES(&temperature_node_process);

PROCESS_THREAD(temperature_node_process, ev, data)
{
  static struct etimer periodic_timer;
  static uip_ip6addr_t dest_ipaddr;
  static char buf[300];

  PROCESS_BEGIN();

  uip_ip6addr(&dest_ipaddr, 0xaaaa, 0, 0, 0, 0, 0, 0, 0x0001);
  simple_udp_register(&udp_conn, UDP_PORT, NULL, UDP_PORT, NULL);
  simple_udp_register(&cmd_conn, CMD_PORT, NULL, CMD_PORT, cmd_rx);

  etimer_set(&periodic_timer, send_interval);
  while(1) {
    PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&periodic_timer));

    uint16_t rank = 0;
    char parent[8];
    get_parent_info(parent, sizeof(parent), &rank);

    int16_t  temp_t  = sample_celsius_tenths();
    uint16_t batt    = sample_battery_mv(rank);
    uint32_t ts      = (uint32_t)clock_seconds();
    uint32_t cpu_ms, lpm_ms, tx_ms, rx_ms;
    get_energest(&cpu_ms, &lpm_ms, &tx_ms, &rx_ms);

    int len = snprintf(buf, sizeof(buf),
      "{\"node_id\":\"temp_%02x\",\"temp_tenths\":%d,"
      "\"battery_mv\":%u,\"seq\":%lu,\"timestamp\":%lu,"
      "\"parent\":\"%s\",\"rank\":%u,"
      "\"cpu_ms\":%lu,\"lpm_ms\":%lu,\"tx_ms\":%lu,\"rx_ms\":%lu}",
      linkaddr_node_addr.u8[7], temp_t, batt,
      (unsigned long)seqno++, (unsigned long)ts,
      parent, rank,
      (unsigned long)cpu_ms, (unsigned long)lpm_ms,
      (unsigned long)tx_ms,  (unsigned long)rx_ms);
    if(len > 0) {
      simple_udp_sendto(&udp_conn, buf, (size_t)len + 1, &dest_ipaddr);
      LOG_INFO("TX %s\n", buf);
    }

    etimer_set(&periodic_timer, send_interval);
  }

  PROCESS_END();
}
