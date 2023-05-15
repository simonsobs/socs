#include <stdlib.h>

// ***** Shared PRU addresses *****
// Address for shared variable 'on' to tell that the PRU is still sampling
#define ON_ADDRESS 0x00010000
// Address for shared variable 'counter_overflow' to count the overflows
#define OVERFLOW_ADDRESS 0x00010008

// Counter-specific addresses
// Address to where the packet identifier will be stored
#define ENCODER_READY_ADDRESS 0x00010010
// Address for Counter Packets to start being written to
#define ENCODER_ADDRESS 0x00010018

// Counter packet format data
// Counter header
#define ENCODER_HEADER 0xBAD0
// Size of edges to sample before sending packet
#define ENCODER_COUNTER_SIZE 120

// IEP (Industrial Ethernet Peripheral) Registers
// IEP base address
#define IEP 0x0002e000
// Register IEP Timer configuration
#define IEP_TMR_GLB_CFG ((volatile unsigned long int *)(IEP + 0x00))
// Register to check for counter overflows
#define IEP_TMR_GLB_STS ((volatile unsigned long int *)(IEP + 0x04))
// Register to configure compensation counter
#define IEP_TMR_COMPEN ((volatile unsigned long int *)(IEP + 0x08))
// Register for the IEP counter (32-bit, 200MHz)
#define IEP_TMR_CNT ((volatile unsigned long int *)(IEP + 0x0c))

// Structure to store clock count of edges and
// the number of times the counter has overflowed
struct EncoderInfo {
    unsigned long int header;
    unsigned long int clock[ENCODER_COUNTER_SIZE];
    unsigned long int clock_overflow[ENCODER_COUNTER_SIZE];
    unsigned long int state[ENCODER_COUNTER_SIZE];
};

// Pointer to the 'on' variable
volatile unsigned long int * on = (volatile unsigned long int *) ON_ADDRESS;
// Pointer to the overflow variable
// Overflow variable is updated by IRIG code, incremented everytime the counter overflows
volatile unsigned long int * counter_overflow = (volatile unsigned long int *) OVERFLOW_ADDRESS;

// Pointer to packet identifier and overflow variable
volatile unsigned long int * encoder_ready = (volatile unsigned long int *) ENCODER_READY_ADDRESS;
// Pointer to complete packet structure
volatile struct EncoderInfo * encoder_packets = (volatile struct EncoderInfo *) ENCODER_ADDRESS;

//  ***** LOCAL VARIABLES *****
// Variables for indexing information
unsigned long int packet = 0;
unsigned long int index = 0;

// Registers to use for PRU input/output
// __R31 is input, __R30 is output
volatile register unsigned int __R31, __R30;


int main(void) {
    unsigned long int pru_mask = (1<<0) | (1<<1) | (1<<2) | (1<<3) | (1<<4) | (1<<5);

    *encoder_ready = 0;
    *counter_overflow = 0;

    encoder_packets[0].header = ENCODER_HEADER;
    encoder_packets[1].header = ENCODER_HEADER;

    // Clears Overflow Flags
    *IEP_TMR_GLB_STS = 1;
    // Enables IEP counter to increment by 1 every cycle
    *IEP_TMR_GLB_CFG = 0x11;
    // Disables compensation counter
    *IEP_TMR_COMPEN = 0;

    // IRIG controls on variable
    // Once the IRIG code has sampled for a given time, it will set *on to 1
    while(*on == 0) {
        if (*IEP_TMR_GLB_STS & 1) {
            (*counter_overflow)++;
            *IEP_TMR_GLB_STS = 1;
        }

        encoder_packets[packet].clock[index] = *IEP_TMR_CNT;
        encoder_packets[packet].clock_overflow[index] = *counter_overflow + (*IEP_TMR_GLB_STS & 1);
        encoder_packets[packet].state[index] = __R31 & pru_mask;

        ++index;
        if (index == ENCODER_COUNTER_SIZE) {
            index = 0;
            *encoder_ready = packet + 1;
            packet = (packet ^ 1) & 1;
        }
        __delay_cycles(25000);
    }
    // Reset PRU input
    __R31 = 0x28;
    // Stop PRU data taking
    __halt();
}

