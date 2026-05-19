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

#define LOG_MODULE "NOISE"
#define LOG_LEVEL  LOG_LEVEL_INFO

#define UDP_PORT  8765
#define CMD_PORT  8766
#define SEND_INTERVAL (10 * CLOCK_SECOND)

static struct simple_udp_connection udp_conn;
static struct simple_udp_connection cmd_conn;
static uint16_t battery_mv    = 3000;
static uint32_t seqno         = 0;
static clock_time_t send_interval = SEND_INTERVAL;

/*
 * Diurnal noise model — correlates with traffic hours (same as PM2.5).
 *   Rush-hours 07-09 / 17-19 : 65-90 dB (heavy traffic, pedestrians)
 *   Night 22-05              : 40-55 dB (near-silence)
 *   Daytime                  : 50-70 dB (light urban activity)
 */
static uint16_t sample_noise_db(void)
{
  uint32_t sim_sec = (uint32_t)clock_seconds();
  uint32_t vhour   = (6 + sim_sec / 3600) % 24;
  uint16_t base;
  if((vhour >= 7 && vhour < 9) || (vhour >= 17 && vhour < 19))
    base = 78;    /* rush-hour: loud traffic + horns         */
  else if(vhour >= 22 || vhour < 5)
    base = 43;    /* night: quiet streets                    */
  else
    base = 58;    /* daytime: moderate activity              */
  int16_t jitter = (int16_t)(random_rand() % 21) - 10; /* ±10 dB */
  int16_t v = (int16_t)base + jitter;
  if(v < 30) v = 30;
  if(v > 100) v = 100;
  return (uint16_t)v;
}

/*
 * Battery drain tied to RPL rank.
 */
static uint16_t sample_battery_mv(uint16_t rank)
{
  uint16_t hop   = rank / 256;
  uint16_t r     = random_rand() % 100;
  uint16_t drain = 0;
  if(r < 25) {
    drain = 0;
  } else if(r < 75) {
    drain = 1 + hop;
  } else {
    drain = 2 + hop * 2;
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

PROCESS(noise_node_process, "Noise node");
AUTOSTART_PROCESSES(&noise_node_process);

PROCESS_THREAD(noise_node_process, ev, data)
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

    uint16_t noise_db = sample_noise_db();
    uint16_t batt     = sample_battery_mv(rank);
    uint32_t ts       = (uint32_t)clock_seconds();
    uint32_t cpu_ms, lpm_ms, tx_ms, rx_ms;
    get_energest(&cpu_ms, &lpm_ms, &tx_ms, &rx_ms);

    int len = snprintf(buf, sizeof(buf),
      "{\"node_id\":\"noise_%02x\",\"noise_db\":%u,"
      "\"battery_mv\":%u,\"seq\":%lu,\"timestamp\":%lu,"
      "\"parent\":\"%s\",\"rank\":%u,"
      "\"cpu_ms\":%lu,\"lpm_ms\":%lu,\"tx_ms\":%lu,\"rx_ms\":%lu}",
      linkaddr_node_addr.u8[7], noise_db, batt,
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
