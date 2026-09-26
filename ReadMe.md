#Progress Till Now

The code compiles using Zephyr, and is able to launch on qemu-arm.

Build Command: west build -p -b mps2/an521/cpu0 .

#Bug

Step 1: I run the built file using the command: qemu-system-arm -M mps2-an521 -cpu cortex-m33 \
    -kernel ./build/zephyr/zephyr.elf \
    -nographic -serial pty -serial pty


Step 2: I attach the provided UART terminal with bluetooth HCI using the command: sudo btattach -B /dev/pts/8 -S 115200 -P h4 -N
(Here, serial port is /dev/pts/8)


Step 3: When I do hciconfig -a
hci1:	Type: Primary  Bus: UART
	BD Address: 00:00:00:00:00:00  ACL MTU: 0:0  SCO MTU: 0:0
	DOWN 
	RX bytes:0 acl:0 sco:0 events:0 errors:0
	TX bytes:4 acl:0 sco:0 commands:1 errors:0
	Features: 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00
	Packet type: DM1 DH1 HV1 
	Link policy: 
	Link mode: PERIPHERAL ACCEPT 
i.e., the bluetooth link is down. hence, the python script is unable to run, and I am not able to see any logs either


Other hints: Output of btmon:
= New Index: 00:00:00:00:00:00 (Primary,UART,hci1)                     [hci1] 7.239913
= Open Index: 00:00:00:00:00:00                                        [hci1] 7.239966
< HCI Command: Reset (0x03|0x0003) plen 0                           #1 [hci1] 7.240045
= Close Index: 00:00:00:00:00:00                                       [hci1] 9.246363


