#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include <prussdrv.h>
#include <pruss_intc_mapping.h>

#include <string.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#define PORT 8040

#define PRUSS_INTC_CUSTOM { \
	{ PRU0_PRU1_INTERRUPT, PRU1_PRU0_INTERRUPT, PRU0_ARM_INTERRUPT, \
	  PRU1_ARM_INTERRUPT, ARM_PRU0_INTERRUPT, ARM_PRU1_INTERRUPT, 24, (char)-1 }, \
	{ {PRU0_PRU1_INTERRUPT, CHANNEL1}, {PRU1_PRU0_INTERRUPT, CHANNEL0}, \
	  {PRU0_ARM_INTERRUPT, CHANNEL2}, {PRU1_ARM_INTERRUPT, CHANNEL3}, \
	  {ARM_PRU0_INTERRUPT, CHANNEL0}, {ARM_PRU1_INTERRUPT, CHANNEL1}, \
	  {24, CHANNEL3}, {-1,-1}}, \
	{ {CHANNEL0, PRU0}, {CHANNEL1, PRU1}, {CHANNEL2, PRU_EVTOUT0}, \
	  {CHANNEL3, PRU_EVTOUT1}, {-1,-1}}, \
	(PRU0_HOSTEN_MASK | PRU1_HOSTEN_MASK | PRU_EVTOUT0_HOSTEN_MASK | PRU_EVTOUT1_HOSTEN_MASK) \
}

#define ENCODER_COUNTER_SIZE 120

#define ENCODER_PACKETS_TO_SEND 1
#define LIMIT_PACKETS_TO_SEND 1
#define ERROR_PACKETS_TO_SEND 1
#define TIMEOUT_PACKETS_TO_SEND 1

#define ON_OFFSET 0x0000
#define OVERFLOW_OFFSET 0x0008
#define ENCODER_READY_OFFSET 0x0010
#define ENCODER_OFFSET 0x0018
#define LIMIT_READY_OFFSET 0x1850
#define LIMIT_OFFSET 0x1858
#define ERROR_READY_OFFSET 0x2000
#define ERROR_OFFSET 0x2008

#define READOUT_BYTES 4

#define ENCODER_TIMEOUT 10
#define LIMIT_TIMEOUT 10

#define ENCODER_TIMEOUT_FLAG 1

volatile int32_t * init_prumem() {
	volatile int32_t * p;
	prussdrv_map_prumem(PRUSS0_SHARED_DATARAM, (void**)&p);
	return p;
}

struct EncoderInfo {
	unsigned long int header;
	unsigned long int clock[ENCODER_COUNTER_SIZE];
	unsigned long int clock_overflow[ENCODER_COUNTER_SIZE];
	unsigned long int state[ENCODER_COUNTER_SIZE];
};

struct LimitInfo {
	unsigned long int header;
	unsigned long int clock;
	unsigned long int clock_overflow;
	unsigned long int state;
};

struct ErrorInfo {
	unsigned long int header;
	unsigned long int error_code;
};

struct TimeoutInfo {
	unsigned long int header;
	unsigned long int type;
};

volatile unsigned long int * on;
volatile unsigned long int * clock_overflow;
volatile unsigned long int * encoder_ready;
volatile struct EncoderInfo * encoder_packets;
volatile unsigned long int * limit_ready;
volatile struct LimitInfo * limit_packets;
volatile unsigned long int * error_ready;
volatile struct ErrorInfo * error_packets;

volatile struct EncoderInfo encoder_to_send[ENCODER_PACKETS_TO_SEND];
volatile struct LimitInfo limit_to_send[LIMIT_PACKETS_TO_SEND];
volatile struct ErrorInfo error_to_send[ERROR_PACKETS_TO_SEND];
volatile struct TimeoutInfo timeout_packet[TIMEOUT_PACKETS_TO_SEND];

unsigned long int offset;
unsigned long int encoder_index, limit_index, error_index;

clock_t current_time, encoder_time;

int sockfd;
struct sockaddr_in servaddr;
int tos_write = 0b10100100;
int tos_read;
int tos_read_len = sizeof(tos_read);


int main(int argc, char **argv) {
	system("./pinconfig");

	if (argc != 5) {
		printf("Usage: %s loader Encoder1.bin \
			Encoder2.bin Limit1.bin Limit2.bin\n", argv[0]);
		return 1;
	}

	prussdrv_init();
	if (prussdrv_open(PRU_EVTOUT_1) == -1) {
		printf("prussdrv_open() failed\n");
		return 1;
	}
	
	tpruss_intc_initdata pruss_intc_initdata = PRUSS_INTC_CUSTOM;
	prussdrv_pruintc_init(&pruss_intc_initdata);
	
	on = (volatile unsigned long *) (init_prumem() + (ON_OFFSET / READOUT_BYTES));
	clock_overflow = (volatile unsigned long *) (init_prumem() + (OVERFLOW_OFFSET / READOUT_BYTES));
	encoder_ready = (volatile unsigned long *) (init_prumem() + (ENCODER_READY_OFFSET / READOUT_BYTES));
	encoder_packets = (volatile struct EncoderInfo *) (init_prumem() + (ENCODER_OFFSET / READOUT_BYTES));
	limit_ready = (volatile unsigned long *) (init_prumem() + (LIMIT_READY_OFFSET / READOUT_BYTES));
	limit_packets = (volatile struct LimitInfo *) (init_prumem() + (LIMIT_OFFSET / READOUT_BYTES));
	error_ready = (volatile unsigned long int *) (init_prumem() + (ERROR_READY_OFFSET / READOUT_BYTES));
	error_packets = (volatile struct ErrorInfo *) (init_prumem() + (ERROR_OFFSET / READOUT_BYTES));

	memset((struct EncoderInfo *) &encoder_packets[0], 0, sizeof(*encoder_packets));
	memset((struct EncoderInfo *) &encoder_packets[1], 0, sizeof(*encoder_packets));
	memset((struct LimitInfo *) &limit_packets[0], 0, sizeof(*limit_packets));
	memset((struct LimitInfo *) &limit_packets[1], 0, sizeof(*limit_packets));
	memset((struct ErrorInfo *) &error_packets[0], 0, sizeof(*error_packets));

	*encoder_ready = 0;
	*limit_ready = 0;
	*error_ready = 0;
	*on = 0;

	printf("Initializing PRU0\n");
	if (argc > 2) {
		if (prussdrv_load_datafile(0, argv[2]) < 0) {
			fprintf(stderr, "Error loading %s\n", argv[2]);
			exit(-1);
		}
	}

	if (prussdrv_exec_program(0, argv[1]) < 0) {
		fprintf(stderr, "Error loading %s\n", argv[1]);
		exit(-1);
	}

	printf("Initializing PRU1\n");
	if (argc == 5) {
		if (prussdrv_load_datafile(1, argv[4]) < 0) {
			fprintf(stderr, "Error loading %s\n", argv[2]);
			exit(-1);
		}
	}

	if (prussdrv_exec_program(1, argv[3]) < 0) {
		fprintf(stderr, "Error loading %s\n", argv[1]);
		exit(-1);
	}

	if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
		perror("socket creation failed");
		exit(EXIT_FAILURE);
	}
	memset(&servaddr, 0, sizeof(servaddr));
	servaddr.sin_family = AF_INET;
	servaddr.sin_port = htons(PORT);
	inet_pton(AF_INET, "192.168.7.2", &(servaddr.sin_addr.s_addr));
	setsockopt(sockfd, IPPROTO_IP, IP_TOS, &tos_write, sizeof(tos_write));
	getsockopt(sockfd, IPPROTO_IP, IP_TOS, &tos_read, &tos_read_len);
	printf("IP UDP TOS byte set to 0x%X\n", tos_read);
	printf("   Precedence = 0x%X\n", (tos_read >> 5) & 0x7);
	printf("   TOS = 0x%X\n", (tos_read >> 1) & 0xF);

	timeout_packet->header = 0x1234;
	encoder_index = 0;
	limit_index = 0;
	error_index = 0;
	current_time = clock();

	printf("Initializing DAQ\n");
	while(*on != 1) {
		current_time = clock();

		if (*encoder_ready != 0) {
			offset = *encoder_ready - 1;
			encoder_to_send[encoder_index] = encoder_packets[offset];
			++encoder_index;
			*encoder_ready = 0;
			encoder_time = current_time;
		}

		if (*limit_ready != 0) {
			offset = *limit_ready - 1;
			limit_to_send[limit_index] = limit_packets[offset];
			printf("%X\n", limit_packets[offset].state);
			++limit_index;
			*limit_ready = 0;
		}

		if (*error_ready != 0) {
			offset = *error_ready - 1;
			error_to_send[error_index] = error_packets[offset];
			++error_index;
			*error_ready = 0;
		}

		if (encoder_index == ENCODER_PACKETS_TO_SEND) {
			sendto(sockfd, (struct EncoderInfo *) encoder_to_send, sizeof(encoder_to_send),
			       MSG_CONFIRM, (const struct sockaddr *) &servaddr, sizeof(servaddr));
			encoder_index = 0;
		}

		if (limit_index == LIMIT_PACKETS_TO_SEND) {
			printf("%lu: sending limit packets\n", current_time);
			sendto(sockfd, (struct LimitInfo *) limit_to_send, sizeof(limit_to_send),
			       MSG_CONFIRM, (const struct sockaddr *) &servaddr, sizeof(servaddr));
			limit_index = 0;
		}

		if (error_index == ERROR_PACKETS_TO_SEND) {
			printf("%lu: sending error packets\n", current_time);
			sendto(sockfd, (struct ErrorInfo *) error_to_send, sizeof(error_to_send),
			       MSG_CONFIRM, (const struct sockaddr *) &servaddr, sizeof(servaddr));
			error_index = 0;
		}

		if (((double) (current_time - encoder_time))/CLOCKS_PER_SEC > ENCODER_TIMEOUT) {
			printf("%lu: sending encoder timeout packet\n", current_time);
			timeout_packet->type = ENCODER_TIMEOUT_FLAG;
			sendto(sockfd, (struct TimeoutInfo *) &timeout_packet, sizeof(*timeout_packet),
			MSG_CONFIRM, (const struct sockaddr *) &servaddr, sizeof(servaddr));
			encoder_time = current_time;
		}
	}

	if (*on == 1) {	
		prussdrv_pru_wait_event(PRU_EVTOUT_1);
		printf("All done\n");
		prussdrv_pru_disable(1);
		prussdrv_pru_disable(0);
		prussdrv_exit();
	}

	return 0;
}
