ORG ?= 2000
BUILD ?= build
C = src/kimdos/c
IMAGES = src/kimdos/images
IMAGE_ORGS = 0400 2000 C000
AS = ca65
AFLAGS = -I asm/include -g
LIB = $(BUILD)/kimdos.lib
LIBSRC = $(wildcard asm/lib/*.s)
LIBOBJ = $(LIBSRC:asm/lib/%.s=$(BUILD)/lib/%.o)

MOS_IMAGE ?= $(shell sed -n "s/^FROM //p" $(C)/Dockerfile)
MOS_RUN ?= docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR):$(CURDIR) -w $(CURDIR)
MOS_CC ?= $(MOS_RUN) $(MOS_IMAGE) mos-common-clang
MOS_AR ?= $(MOS_RUN) --entrypoint llvm-ar $(MOS_IMAGE)
MOS_CFLAGS = -Os -flto -Wall -Wextra -Werror -I $(C)/include
CBUILD = $(BUILD)/c
CLIBOBJ = $(addprefix $(CBUILD)/,iec.o con.o dos.o dir.o)

.PHONY: all clean clib images
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

clib: $(CBUILD)/libkimdos.a $(CBUILD)/kdtest.bin

$(CBUILD)/%.o: $(C)/src/%.s
	@mkdir -p $(@D)
	$(MOS_CC) -c -o $@ $<

$(CBUILD)/%.o: $(C)/src/%.c $(C)/src/kdint.h $(C)/include/kimdos.h
	@mkdir -p $(@D)
	$(MOS_CC) $(MOS_CFLAGS) -c -o $@ $<

$(CBUILD)/crt.o: $(C)/kim1/crt.s
	@mkdir -p $(@D)
	$(MOS_CC) -c -o $@ $<

$(CBUILD)/libkimdos.a: $(CLIBOBJ)
	rm -f $@
	$(MOS_AR) rcs $@ $^

$(CBUILD)/kdtest.bin: $(C)/test/kdtest.c $(CBUILD)/crt.o $(CBUILD)/libkimdos.a $(C)/kim1/link.ld
	$(MOS_CC) $(MOS_CFLAGS) -T $(C)/kim1/link.ld -o $(@:.bin=) $< $(CBUILD)/crt.o $(CBUILD)/libkimdos.a
	mv $(@:.bin=) $@

# The shell images packaged in the wheel.
images:
	for org in $(IMAGE_ORGS); do $(MAKE) ORG=$$org || exit 1; done
	mkdir -p $(IMAGES)
	cp $(foreach o,$(IMAGE_ORGS),$(addprefix $(BUILD)/kimdos-$(o).,bin ptp lbl)) $(IMAGES)/

clean:
	rm -rf $(BUILD) $(IMAGES)
