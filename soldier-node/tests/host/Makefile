# core/ 호스트 단위 테스트. 사용: make -C tests/host
CXX      ?= g++
CC       ?= cc
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror -O1
CORE     := ../../firmware/SoldierNode/src/core
CORE_SRC := $(wildcard $(CORE)/*.cpp)
CORE_HDR := $(wildcard $(CORE)/*.h)
# app/ 중 Arduino 비의존 모듈(호스트 테스트 대상)
APP      := ../../firmware/SoldierNode/src/app
APP_SRC  := $(APP)/phrases.cpp $(APP)/squad_map.cpp
TESTS    := test_frame test_crc_adpcm test_geo test_queue test_input test_phrases test_unack test_earpiece test_ranging test_squad
BUILD    := build

all: c-check ascii-check run

$(BUILD)/%: %.cpp test_util.h $(CORE_SRC) $(CORE_HDR) $(APP_SRC) | $(BUILD)
	$(CXX) $(CXXFLAGS) -I$(CORE) -I$(APP) $< $(CORE_SRC) $(APP_SRC) -o $@

$(BUILD):
	mkdir -p $@

# core가 C(C99)로도 컴파일되는지(Arduino 비의존, C 호환) 문법 검사
c-check:
	@for f in $(CORE_SRC); do $(CC) -x c -std=c99 -Wall -Wextra -Werror -pedantic -fsyntax-only -I$(CORE) $$f || exit 1; done
	@echo "core C99 syntax check OK"

# 펌웨어 문자열 리터럴 ASCII 검사(LOG는 ASCII 전용)
ascii-check:
	@python3 check_ascii.py ../../firmware/SoldierNode

run: $(addprefix $(BUILD)/,$(TESTS))
	@for t in $^; do echo "== $$t"; ./$$t || exit 1; done
	@echo "ALL HOST TESTS PASSED"

clean:
	rm -rf $(BUILD)

.PHONY: all c-check ascii-check run clean
