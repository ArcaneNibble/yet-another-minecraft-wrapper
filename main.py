#!/usr/bin/env python3

import asyncio
import asyncio.subprocess
import bottom
import json
import sys

class MinecraftServerWrapper:
    _config = None
    _loop = None
    _bottom = None
    _subprocess = None

    def __init__(self, config, loop):
        self._config = config
        self._loop = loop

    # Create the subprocess
    async def subprocess_create(self):
        self._subprocess = await asyncio.create_subprocess_exec(
            *self._config["cmdline"],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        print(self._subprocess)

        while True:
            # Read from the process
            output_line = await self._subprocess.stdout.readline()

            if output_line:
                print(output_line)
            else:
                # Killed?
                print(self._subprocess.returncode)
                return

    # Actual work starts here
    async def start_wrapper(self):
        print("Attempting to connect to IRC...")

        # Create bottom IRC client
        self._bottom = bottom.Client(host=self._config["irc_server"],
                                     port=self._config["irc_port"],
                                     ssl=False)

        # Basic IRC handlers
        @self._bottom.on('NOTICE')
        def irc_notice(message, **kwargs):
            print(message)

        @self._bottom.on('PING')
        def keepalive(message, **kwargs):
            bot.send('PONG', message=message)

        # Connect and then send username
        await self._bottom.connect()
        self._bottom.send('NICK', nick=self._config["irc_nick"])
        self._bottom.send('USER', user=self._config["irc_nick"],
                          realname=self._config["irc_nick"])

        print("Waiting for IRC MOTD...")

        # Wait on MOTD
        done, pending = await asyncio.wait(
            [self._bottom.wait("RPL_ENDOFMOTD"),
             self._bottom.wait("ERR_NOMOTD")],
            loop=self._loop,
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel whichever waiter's event didn't come in.
        for future in pending:
            future.cancel()

        print("Joining channel...")

        self._bottom.send('JOIN', channel=self._config["irc_channel"])

        # Register message handler
        @self._bottom.on('PRIVMSG')
        def message(nick, target, message, **kwargs):
            # User must be authorized
            if nick not in self._config["users"]:
                return

            fragments = message.strip().split(maxsplit=2)
            if len(fragments) != 3:
                return

            # Command must start with "!<nick>" or "!!<nick>"
            if ((fragments[0] != ("!" + self._config["irc_nick"])) and
                (fragments[0] != ("!!" + self._config["irc_nick"]))):
                return
            is_special_cmd = fragments[0][:2] == "!!"

            # TODO: sig

            # Actual command
            real_command = fragments[2]
            print(is_special_cmd, real_command)

        print("IRC ready!")

        # Launch subprocess
        self._loop.create_task(self.subprocess_create())

def main():
    if len(sys.argv) < 2:
        print("Usage: {} config.json".format(sys.argv[0]))
        return

    # Load config
    with open(sys.argv[1], 'r') as f:
        config = json.load(f)

    # Start event loop
    loop = asyncio.get_event_loop()
    serv = MinecraftServerWrapper(config, loop)
    loop.create_task(serv.start_wrapper())
    loop.run_forever()

if __name__ == '__main__':
    main()
