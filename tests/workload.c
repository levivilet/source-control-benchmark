#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void wait_for(const char *path) {
  while (access(path, F_OK) != 0) usleep(1000);
}

static void loop(uint64_t count) {
  volatile uint64_t value = 1;
  for (uint64_t i = 0; i < count; i++) value = value * 3 + i;
  (void)value;
}

int main(int argc, char **argv) {
  if (argc != 7) return 2;
  const char *mode = argv[1];
  const char *ready = argv[2];
  const char *go = argv[3];
  const char *done = argv[4];
  const char *release = argv[5];
  uint64_t before = strtoull(argv[6], NULL, 10);
  int detached = mode[0] == 'd';
  pid_t child = detached ? fork() : 0;
  if (child < 0) return 3;
  if (detached && child > 0) {
    FILE *file = fopen(ready, "w");
    if (!file) return 4;
    fclose(file);
    wait_for(go);
    if (waitpid(child, NULL, 0) < 0) return 5;
    return 0;
  }
  FILE *file = fopen(ready, "w");
  if (!file) return 4;
  fclose(file);
  wait_for(go);
  loop(before);
  file = fopen(done, "w");
  if (!file) return 6;
  fclose(file);
  wait_for(release);
  loop(before * 10);
  return 0;
}
