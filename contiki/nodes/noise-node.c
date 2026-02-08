#include "contiki.h"
#include "net/ipv6/simple-udp.h"
#include "sys/log.h"
#include "sys/etimer.h"
#include "lib/random.h"
#include "net/routing/routing.h"
#include "net/routing/rpl-lite/rpl.h"
#include "net/linkaddr.h"
#include <stdio.h>

#define LOG_MODULE "NOISE"
#define LOG_LEVEL LOG_LEVEL_INFO

#define UDP_PORT 8765
#define SEND_INTERVAL (10 * CLOCK_SECOND)

static struct simple_udp_connection udp_conn;
static uint16_t battery_mv = 3000;
static uint32_t seqno = 0;

static uint16_t sample_noise_db(void) {
  /* pseudo sensor: 40-90 dB range */
  return 40 + (random_rand() % 50);
}

static uint16_t sample_battery_mv(void) {
  /* Realistic drain: ~0.1-0.3 mV per packet. */
  uint16_t r = random_rand() % 100;
  if(r < 30) {
    /* 30% chance of no drop */
  } else if(r < 80) {
    /* 50% chance of tiny drop */
    if(battery_mv > 1) battery_mv -= 1;
  } else {
    /* 20% chance of larger drop */
    if(battery_mv > 2) battery_mv -= 2;
  }
  return battery_mv;
}

static void get_parent_info(char *parent_buf, size_t parent_len, uint16_t *rank_out) {
  *rank_out = curr_instance.dag.rank;
  rpl_nbr_t *pref = curr_instance.dag.preferred_parent;
  if(pref != NULL) {
    const uip_ipaddr_t *parent_ip = rpl_neighbor_get_ipaddr(pref);
    if(parent_ip != NULL) {
      snprintf(parent_buf, parent_len, "%02x%02x",
               parent_ip->u8[14], parent_ip->u8[15]);
      return;
    }
  }
  snprintf(parent_buf, parent_len, "none");
}

PROCESS(noise_node_process, "Noise node");
AUTOSTART_PROCESSES(&noise_node_process);

PROCESS_THREAD(noise_node_process, ev, data) {
  static struct etimer periodic_timer;
  static uip_ip6addr_t dest_ipaddr;
  static char buf[192];

  PROCESS_BEGIN();

  uip_ip6addr(&dest_ipaddr, 0xaaaa, 0, 0, 0, 0, 0, 0, 0x0001);
  simple_udp_register(&udp_conn, UDP_PORT, NULL, UDP_PORT, NULL);

  etimer_set(&periodic_timer, SEND_INTERVAL);
  while(1) {
    PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&periodic_timer));
    uint16_t noise_db = sample_noise_db();
    uint16_t batt = sample_battery_mv();
    uint32_t ts = (uint32_t)clock_seconds();
    uint16_t rank = 0;
    char parent[8];
    get_parent_info(parent, sizeof(parent), &rank);

    int len = snprintf(buf, sizeof(buf),
               "{\"node_id\":\"noise_%02x\",\"noise_db\":%u,\"battery_mv\":%u,\"seq\":%lu,\"timestamp\":%lu,\"parent\":\"%s\",\"rank\":%u}",
               linkaddr_node_addr.u8[7], noise_db, batt,
               (unsigned long)seqno++, (unsigned long)ts,
               parent, rank);
    if(len > 0) {
      simple_udp_sendto(&udp_conn, buf, (size_t)len + 1, &dest_ipaddr);
      LOG_INFO("TX %s\n", buf);
    }

    etimer_reset(&periodic_timer);
  }

  PROCESS_END();
}
