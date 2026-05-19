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

#define LOG_MODULE "POLL"
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
 * Diurnal PM2.5 model.
 * Simulation starts at virtual 06:00.
 * Rush-hours 07-09 and 17-19 produce higher PM2.5 (traffic).
 */
static uint16_t sample_pm25(void)
{
  uint32_t sim_sec = (uint32_t)clock_seconds();
  uint32_t vhour   = (6 + sim_sec / 3600) % 24;
  uint16_t base;
  if((vhour >= 7 && vhour < 9) || (vhour >= 17 && vhour < 19))
    base = 95;    /* rush-hour: heavy vehicle traffic */
  else if(vhour >= 22 || vhour < 5)
    base = 35;    /* night: minimal traffic           */
  else
    base = 62;    /* daytime average                  */
  int16_t jitter = (int16_t)(random_rand() % 25) - 12; /* ±12 µg/m³ */
  int16_t v = (int16_t)base + jitter;
  return (v < 0) ? 0 : (uint16_t)v;
}

/*
 * Battery drain tied to RPL rank.
 * RPL rank unit = 256; deeper nodes experience more retransmissions.
 */
static uint16_t sample_battery_mv(uint16_t rank)
{
  uint16_t hop   = rank / 256;        /* 0 = 1-hop, 1 = 2-hop, etc. */
  uint16_t r     = random_rand() % 100;
  uint16_t drain = 0;
  if(r < 25) {
    drain = 0;                         /* idle / power-save cycle     */
  } else if(r < 75) {
    drain = 1 + hop;                   /* normal single-hop TX        */
  } else {
    drain = 2 + hop * 2;               /* burst / retransmission      */
  }
  if(battery_mv > drain) battery_mv -= drain; else battery_mv = 0;
  return battery_mv;
}

/* Read cumulative energest counters and convert to milliseconds. */
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
 * Adjusts send_interval proportionally.
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

PROCESS(pollution_node_process, "Pollution node");
AUTOSTART_PROCESSES(&pollution_node_process);

PROCESS_THREAD(pollution_node_process, ev, data)
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

    uint16_t pm25 = sample_pm25();
    uint16_t batt = sample_battery_mv(rank);
    uint32_t ts   = (uint32_t)clock_seconds();
    uint32_t cpu_ms, lpm_ms, tx_ms, rx_ms;
    get_energest(&cpu_ms, &lpm_ms, &tx_ms, &rx_ms);

    int len = snprintf(buf, sizeof(buf),
      "{\"node_id\":\"poll_%02x\",\"pm25\":%u,"
      "\"battery_mv\":%u,\"seq\":%lu,\"timestamp\":%lu,"
      "\"parent\":\"%s\",\"rank\":%u,"
      "\"cpu_ms\":%lu,\"lpm_ms\":%lu,\"tx_ms\":%lu,\"rx_ms\":%lu}",
      linkaddr_node_addr.u8[7], pm25, batt,
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
