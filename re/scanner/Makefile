# TH80 V2 pin scanner — bare-metal CH584, loads at 0x5000 (vendor boot preserved)
TC   := ../../toolchain/riscv-none-elf-gcc/bin/riscv-none-elf-
CC   := $(TC)gcc
OBJCOPY := $(TC)objcopy
SIZE := $(TC)size
SDK  := ../wch_sdk/EVT/EXAM/SRC

ARCH := -march=rv32imac -mabi=ilp32 -mcmodel=medany -msmall-data-limit=8 -mno-save-restore
CFLAGS := $(ARCH) -std=gnu99 -Os -g -ffunction-sections -fdata-sections \
          -I$(SDK)/StdPeriphDriver/inc -I$(SDK)/RVMSIS -I.
LDFLAGS := $(ARCH) -T Link.ld -nostartfiles -Wl,--gc-sections -Wl,-Map=scanner.map

DRV := $(SDK)/StdPeriphDriver
CSRC := Main.c $(DRV)/CH58x_clk.c $(DRV)/CH58x_gpio.c $(DRV)/CH58x_sys.c \
        $(DRV)/CH58x_usbdev.c $(DRV)/CH58x_pwr.c $(DRV)/CH58x_spi0.c $(DRV)/CH58x_adc.c
ASRC := startup_CH585.S
LIBS := $(DRV)/libISP585.a

OBJ := $(CSRC:.c=.o) $(ASRC:.S=.o)

all: scanner.bin combined.bin

scanner.elf: $(OBJ) Link.ld
	$(CC) $(LDFLAGS) $(OBJ) $(LIBS) -o $@
	$(SIZE) $@

scanner.bin: scanner.elf
	$(OBJCOPY) -O binary $< $@

# Vendor boot (0x0-0x5000) + scanner, for wchisp via the J2 boot jumper.
combined.bin: scanner.bin ../../firmware/3720_v107.bin
	head -c 20480 ../../firmware/3720_v107.bin > $@
	cat scanner.bin >> $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.S
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJ) scanner.elf scanner.bin scanner.map combined.bin

.PHONY: all clean
