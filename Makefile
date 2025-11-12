.PHONY: all deps clean

PERL          := perl
LOCAL_LIB     := $(CURDIR)/local
CPANM         := $(LOCAL_LIB)/bin/cpanm
FATPACK       := $(LOCAL_LIB)/bin/fatpack

APP_PL        := auto.pl
APP_EXE       := build/auto
APP_COMP      := zsh-auto-script

TARGET_PREFIX := $(HOME)/.local
TARGET_EXE    := $(TARGET_PREFIX)/bin/auto
TARGET_CUSTOM := $(TARGET_PREFIX)/share/zshcustom
TARGET_COMP   := $(TARGET_CUSTOM)/zsh-auto-script

export PERL5LIB=$(LOCAL_LIB)/lib/perl5
export PERL_LOCAL_LIB_ROOT=$(LOCAL_LIB)
export PERL_MB_OPT=--install_base $(LOCAL_LIB)
export PERL_MM_OPT=INSTALL_BASE=$(LOCAL_LIB)
export PATH := $(LOCAL_LIB)/bin:$(PATH)

all: build install

$(CPANM):
	$(PERL) -Mlocal::lib=$(LOCAL_LIB) -MCPAN -e 'CPAN::Shell->install("App::cpanminus")'

deps: $(CPANM)
	$(CPANM) --local-lib=$(LOCAL_LIB) --installdeps .

$(APP_EXE): deps $(APP_PL)
	mkdir -p build
	$(FATPACK) pack $(APP_PL) > $(APP_EXE)
	chmod +x $(APP_EXE)

build: $(APP_EXE)

install: $(APP_EXE)
	install -m755 $(APP_EXE) $(TARGET_EXE)
	mkdir -p $(TARGET_CUSTOM)
	rm -rf $(TARGET_COMP)
	cp -r $(APP_COMP) $(TARGET_COMP)

clean:
	rm -rf build local fatlib

