#!/usr/bin/env python3

import asyncio
import bottom
import json
import sys

class MinecraftServerWrapper:
    _config = None
    _loop = None

    def __init__(self, config, loop):
        _config = config
        _loop = loop

    # Actual work starts here
    async def start_wrapper(self):
        print("Start!")

def main():
    if len(sys.argv) < 2:
        print("Usage: {} config.json".format(sys.argv[0]))
        return

    # Load config
    with open(sys.argv[1], 'r') as f:
        config = json.load(f)
    print(config)

    # Start event loop
    loop = asyncio.get_event_loop()
    serv = MinecraftServerWrapper(config, loop)
    loop.create_task(serv.start_wrapper())
    loop.run_forever()

if __name__ == '__main__':
    main()
