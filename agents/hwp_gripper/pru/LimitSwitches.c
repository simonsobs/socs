#include <stdlib.h>

// ********** CONSTANTS **********

// Address for shared variable 'on' to tell ARM when the PRU is still sampling
#define ON_ADDRESS 0x00010000
// Address for shared variable between PRUs to count clock overflows
// Needed since both PRUs share the same clock
#define OVERFLOW_ADDRESS 0x00010008

#define LIMIT_READY_ADDRESS 0x00011850
#define LIMIT_ADDRESS 0x00011858

#define LIMIT_HEADER 0xF00D

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

// ********** STRUCTS **********
struct LimitInfo {
    unsigned long int header;
    unsigned long int clock;
    unsigned long int clock_overflow;
    unsigned long int state;
};

// ********** POINTERS **********

// *** Shared Pointers ***
// Pointer to the 'on' variable: 0 if PRUs are still sampling, 1 if they are done
volatile unsigned long int * on = (volatile unsigned long int *) ON_ADDRESS;
// Identifies when and which clock_overflow struct is ready to be read out
volatile unsigned long int * counter_overflow = (volatile unsigned long int *) OVERFLOW_ADDRESS;

volatile unsigned long int * limit_ready = (volatile unsigned long int *) LIMIT_READY_ADDRESS;
volatile struct LimitInfo * limit_packets = (volatile struct LimitInfo*) LIMIT_ADDRESS;

unsigned long int packet = 0;

// Registers to use for PRU input/output
// __R31 is input, __R30 is output
volatile register unsigned int __R31, __R30;

int main(void)
{
    unsigned long int pru_mask = (1<<8) | (1<<9) | (1<<10) | (1<<11) | (1<<12) | (1<<13);

    *limit_ready = 0;

    limit_packets[0].header = LIMIT_HEADER;
    limit_packets[1].header = LIMIT_HEADER;

    // Clears Overflow Flags
    *IEP_TMR_GLB_STS = 1;
    // Enables IEP counter to increment by 1 every cycle
    *IEP_TMR_GLB_CFG = 0x11;
    // Disables compensation counter
    *IEP_TMR_COMPEN = 0;

    while(*on == 0) {
        if ((~__R31 & pru_mask) != 0) {
            limit_packets[packet].clock = *IEP_TMR_CNT;
            limit_packets[packet].clock_overflow = *counter_overflow + (*IEP_TMR_GLB_STS & 1);
            limit_packets[packet].state = ~__R31 & pru_mask;

            *limit_ready = packet + 1;
            packet = (packet ^ 1) & 1;
            __delay_cycles(12000000);
        }
    }

    // Interrupt ARM when finished
    __R31 = 0x28;
    // Halt the PRU
    __halt();
}
