ORG ?= 2000
BUILD ?= build
AS = ca65
AFLAGS = -I asm/include -g
LIB = $(BUILD)/kimdos.lib
LIBSRC = $(wildcard asm/lib/*.s)
LIBOBJ = $(LIBSRC:asm/lib/%.s=$(BUILD)/lib/%.o)

MOS_IMAGE ?= $(shell sed -n "s/^FROM //p" c/Dockerfile)
MOS_RUN ?= docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR):$(CURDIR) -w $(CURDIR)
MOS_CC ?= $(MOS_RUN) $(MOS_IMAGE) mos-common-clang
MOS_AR ?= $(MOS_RUN) --entrypoint llvm-ar $(MOS_IMAGE)
MOS_CFLAGS = -Os -flto -Wall -Wextra -Werror -I c/include
CBUILD = $(BUILD)/c
CLIBOBJ = $(addprefix $(CBUILD)/,iec.o con.o dos.o dir.o)

.PHONY: all clean clib
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

$(CBUILD)/%.o: c/src/%.s
	@mkdir -p $(@D)
	$(MOS_CC) -c -o $@ $<

$(CBUILD)/%.o: c/src/%.c c/src/kdint.h c/include/kimdos.h
	@mkdir -p $(@D)
	$(MOS_CC) $(MOS_CFLAGS) -c -o $@ $<

$(CBUILD)/crt.o: c/kim1/crt.s
	@mkdir -p $(@D)
	$(MOS_CC) -c -o $@ $<

$(CBUILD)/libkimdos.a: $(CLIBOBJ)
	rm -f $@
	$(MOS_AR) rcs $@ $^

$(CBUILD)/kdtest.bin: c/test/kdtest.c $(CBUILD)/crt.o $(CBUILD)/libkimdos.a c/kim1/link.ld
	$(MOS_CC) $(MOS_CFLAGS) -T c/kim1/link.ld -o $(@:.bin=) $< $(CBUILD)/crt.o $(CBUILD)/libkimdos.a
	mv $(@:.bin=) $@

clean:
	rm -rf $(BUILD)
