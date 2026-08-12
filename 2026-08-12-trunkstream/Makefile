CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11 -Isrc
LDFLAGS =

SRC = src/core/manifest_loader.c \
      src/core/trunk_streamer.c \
      src/core/expert_cache.c \
      src/core/inference_engine.c

OBJ = $(SRC:.c=.o)

TEST_SRC = tests/test_manifest_loader.c \
           tests/test_inference_engine.c

TEST_BIN = $(TEST_SRC:.c=.out)

all: libtrunkstream.a $(TEST_BIN)

libtrunkstream.a: $(OBJ)
	ar rcs $@ $(OBJ)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

$(TEST_BIN): %\.out: %.c libtrunkstream.a
	$(CC) $(CFLAGS) $< -L. -ltrunkstream -o $@

test: $(TEST_BIN)
	@for t in $(TEST_BIN); do echo "Running $$t"; ./$$t || exit 1; done

clean:
	rm -f $(OBJ) libtrunkstream.a $(TEST_BIN)
