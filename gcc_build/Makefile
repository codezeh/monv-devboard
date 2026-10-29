# Makefile for STM32F407VETx -- GNU Arm Embedded Toolchain
# Replaces Keil MDK (which is limited to 32KB in Lite edition)

TOOLCHAIN ?= /d/gcc/arm-gnu-toolchain-13.3.rel1-mingw-w64-i686-arm-none-eabi/bin
PREFIX    := $(TOOLCHAIN)/arm-none-eabi-
CC        := $(PREFIX)gcc
AS        := $(PREFIX)gcc -x assembler-with-cpp
CP        := $(PREFIX)objcopy
SZ        := $(PREFIX)size

SRC_DIR   := ../例程_ST7735/示例代码
BUILD     := build

# ---- sources ----
C_SOURCES := \
  $(SRC_DIR)/User/main.c \
  $(SRC_DIR)/Core/system_stm32f4xx.c \
  $(SRC_DIR)/BSP/LED/bsp_led.c \
  $(SRC_DIR)/BSP/UART/bsp_UART.c \
  $(SRC_DIR)/BSP/KEY/bsp_key.c \
  $(SRC_DIR)/BSP/W25Q128/bsp_spi_flash.c \
  $(SRC_DIR)/BSP/LCD_1.8_ST7735/bsp_LCD_ST7735.c \
  $(SRC_DIR)/BSP/KNOB/bsp_knob.c \
  $(SRC_DIR)/BSP/SKIN/bsp_skin.c \
  $(SRC_DIR)/BSP/SKIN/skin_bust.c \
  $(SRC_DIR)/BSP/SKIN/skin_anim.c

ASM_SOURCES := startup_stm32f407.c

# StdPeriph driver sources (all .c in the driver dir)
STDP_SOURCES := $(wildcard $(SRC_DIR)/STM32F4xx_StdPeriph_Driver/src/*.c)
C_SOURCES += $(STDP_SOURCES)

# ---- includes ----
C_INCLUDES := \
  -I$(SRC_DIR)/User \
  -I$(SRC_DIR)/Core \
  -I$(SRC_DIR)/Core/Startup \
  -I$(SRC_DIR)/STM32F4xx_StdPeriph_Driver/inc \
  -I$(SRC_DIR)/BSP/LED \
  -I$(SRC_DIR)/BSP/UART \
  -I$(SRC_DIR)/BSP/KEY \
  -I$(SRC_DIR)/BSP/W25Q128 \
  -I$(SRC_DIR)/BSP/LCD_1.8_ST7735 \
  -I$(SRC_DIR)/BSP/KNOB \
  -I$(SRC_DIR)/BSP/SKIN

CFLAGS := -mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb \
          -std=gnu11 -O2 -g3 -Wall -fdata-sections -ffunction-sections \
          -DUSE_STDPERIPH_DRIVER -DSTM32F40_41xxx $(C_INCLUDES)

ASFLAGS := -mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb

LDSCRIPT := STM32F407VETx_FLASH.ld
LDFLAGS  := -mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb \
            -T$(LDSCRIPT) -specs=nano.specs -specs=nosys.specs \
            -Wl,--gc-sections -Wl,-Map=$(BUILD)/app.map,--cref \
            -Wl,--print-memory-usage

OBJ := $(addprefix $(BUILD)/,$(notdir $(C_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))
OBJ += $(addprefix $(BUILD)/,$(notdir $(ASM_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(ASM_SOURCES)))

TARGET := $(BUILD)/app

all: $(TARGET).elf $(TARGET).hex $(TARGET).bin
	@$(SZ) $(TARGET).elf

$(BUILD)/%.o: %.c | $(BUILD)
	@echo "  CC  $<"
	@$(CC) -c $(CFLAGS) $< -o $@

$(BUILD)/%.o: %.c | $(BUILD)
	@echo "  AS  $<"
	@$(AS) -c $(ASFLAGS) $< -o $@

$(TARGET).elf: $(OBJ) $(LDSCRIPT) | $(BUILD)
	@echo "  LD  $@"
	@$(CC) $(OBJ) $(LDFLAGS) -o $@

$(TARGET).hex: $(TARGET).elf
	@$(CP) -O ihex $< $@

$(TARGET).bin: $(TARGET).elf
	@$(CP) -O binary -S $< $@

$(BUILD):
	@mkdir -p $@

clean:
	@rm -rf $(BUILD)

.PHONY: all clean
