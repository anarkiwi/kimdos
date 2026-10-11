ORG ?= 2000
BUILD ?= build
AS = ca65
AFLAGS = -I asm/include -g
LIB = $(BUILD)/kimdos.lib
LIBSRC = $(wildcard asm/lib/*.s)
LIBOBJ = $(LIBSRC:asm/lib/%.s=$(BUILD)/lib/%.o)

.PHONY: all clean
all: $(BUILD)/kimdos-$(ORG).bin $(BUILD)/kimdos-$(ORG).ptp

$(BUILD)/lib/%.o: asm/lib/%.s asm/include/kimdos.inc
	@mkdir -p $(@D)
	$(AS) $(AFLAGS) -o $@ $<

$(LIB): $(LIBOBJ)
	rm -f $@
	ar65 a $@ $^

$(BUILD)/app/%.o: asm/app/%.s asm/include/kimdos.inc
	@mkdir -p $(@D)
	$(AS) $(AFLAGS) -o $@ $<

$(BUILD)/kimdos-$(ORG).bin: $(BUILD)/app/shell.o $(LIB) asm/cfg/ram.cfg
	ld65 -C asm/cfg/ram.cfg -D __ORG__=0x$(ORG) -Ln $(@:.bin=.lbl) \
		-m $(@:.bin=.map) -o $@ $(BUILD)/app/shell.o $(LIB)

$(BUILD)/kimdos-$(ORG).ptp: $(BUILD)/kimdos-$(ORG).bin
	kimtape convert $< --at $(ORG) -o $@

clean:
	rm -rf $(BUILD)
