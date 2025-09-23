.PHONY: all deps clean

PERL        := perl
LOCAL_LIB   := $(CURDIR)/local
CPANM       := $(LOCAL_LIB)/bin/cpanm
FATPACK     := $(LOCAL_LIB)/bin/fatpack
APP_PL      := auto.pl
APP_EXE     := build/auto

export PERL5LIB=$(LOCAL_LIB)/lib/perl5
export PERL_LOCAL_LIB_ROOT=$(LOCAL_LIB)
export PERL_MB_OPT=--install_base $(LOCAL_LIB)
export PERL_MM_OPT=INSTALL_BASE=$(LOCAL_LIB)
export PATH := $(LOCAL_LIB)/bin:$(PATH)

all: $(APP_EXE)

$(CPANM):
	$(PERL) -Mlocal::lib=$(LOCAL_LIB) -MCPAN -e 'CPAN::Shell->install("App::cpanminus")'

deps: $(CPANM)
	$(CPANM) --local-lib=$(LOCAL_LIB) --installdeps .

$(APP_EXE): deps $(APP_PL)
	mkdir -p build
	$(FATPACK) pack $(APP_PL) > $(APP_EXE)
	chmod +x $(APP_EXE)

clean:
	rm -rf build local fatlib

