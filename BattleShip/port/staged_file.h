#ifndef PORT_STAGED_FILE_H
#define PORT_STAGED_FILE_H

#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

/* fopen() for roster-provided files (fighter bundles, .osbui packs,
 * announcer clips) that the web shell may not have written into MEMFS yet.
 *
 * On the web the character select can list a thousand fighters; staging
 * every bundle up front would download gigabytes before the engine even
 * boots. Instead the shell registers a URL per MEMFS path
 * (Module.__stageUrls) and this wrapper asks it to fetch the file the first
 * time the engine opens it. Asyncify suspends the caller while
 * Module.ensureStaged fetches asynchronously, leaving the browser responsive.
 * Background prefetch and existing MEMFS files avoid waiting on the network.
 *
 * On native builds this is plain fopen(). */
FILE *port_fopen_staged(const char *path, const char *mode);

#ifdef __cplusplus
}
#endif

#endif
