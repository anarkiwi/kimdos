; KIMDOS library interface.  All routines use registers and the exported
; variables below; none use zero page.

; serial bus primitives (iec.s)
.global iec_listen              ; A = device
.global iec_second              ; A = secondary address after LISTEN
.global iec_talk                ; A = device
.global iec_tksa                ; A = secondary address after TALK
.global iec_ciout               ; A = byte, buffered so UNLISTEN sends EOI
.global iec_acptr               ; -> A = byte
.global iec_unlsn
.global iec_untlk
.global iec_st                  ; status byte, ST_* bits
.global iec_jiffy               ; bit 0: JiffyDOS on (default), 0 forces
                                ; the standard protocol; bit 7: in use
.global iec_jload               ; A/X = address: JiffyDOS LOAD mode stream

; DOS layer (dos.s)
.global dos_dev                 ; device number, default 8
.global dos_setnam              ; A = length, X/Y = address of name
.global dos_open                ; A = channel; C = 1 if no device
.global dos_close               ; A = channel
.global dos_chkin               ; A = channel: TALK it; C = 1 if no device
.global dos_chkout              ; A = channel: LISTEN it; C = 1 if no device
.global dos_getb                ; -> A = byte, C = 1 past end of data
.global dos_read                ; A = channel: read to dos_beg..dos_end
.global dos_write               ; A = channel: write dos_beg..dos_end
.global dos_load                ; A = 0 load / 1 verify; C = 1 to dos_beg
.global dos_save                ; dos_beg..dos_end to the named file
.global dos_cmd                 ; send the name as a command
.global dos_status              ; -> A = code, C = 1 if error, dos_errbuf
.global dos_beg                 ; 2 bytes: first address
.global dos_end                 ; 2 bytes: end address, exclusive
.global dos_errbuf              ; status text, zero terminated

; console helpers over the KIM-1 monitor's TTY routines (con.s)
.global con_putc                ; A preserved, X/Y preserved
.global con_getc                ; -> A, 7-bit; X/Y preserved
.global con_crlf
.global con_pet                 ; print PETSCII A as ASCII
.global con_puts                ; X/Y = zero terminated string
.global con_phex                ; A as two hex digits
.global con_phex16              ; $XXYY with X high, A low
.global con_pdec                ; X/Y = 16-bit value, unsigned decimal

ST_WTO  = $01                   ; write timeout: no frame acknowledge
ST_RTO  = $02                   ; read timeout: talker sent nothing
ST_VER  = $10                   ; verify mismatch
ST_EOI  = $40                   ; last byte received
ST_DNP  = $80                   ; device not present

; KIM-1 monitor
KIM_SAL    = $17F5              ; tape start address
KIM_SAH    = $17F6
KIM_EAL    = $17F7              ; tape end address, exclusive
KIM_EAH    = $17F8
KIM_ID     = $17F9              ; tape ID
KIM_POINTL = $FA                ; displayed / opened address
KIM_POINTH = $FB
KIM_START  = $1C4F
KIM_GETCH  = $1E5A
KIM_OUTCH  = $1EA0
