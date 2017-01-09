#!/usr/bin/env python3

import asyncio
import asyncio.subprocess
import bottom
import json
import re
import string
import sys


IRC_TO_MC_HEX_LUT = [
    "§f",   # White
    "§0",   # Black
    "§1",   # Dark blue
    "§2",   # Dark green
    "§c",   # Red
    "§4",   # Dark red
    "§5",   # Dark purple
    "§6",   # Gold
    "§e",   # Yellow
    "§a",   # Green
    "§3",   # Dark aqua
    "§b",   # Aqua
    "§9",   # Blue
    "§d",   # Light purple
    "§8",   # Dark gray
    "§7",   # Gray
]

IRC_TO_MC_NAME_LUT = [
    "white",
    "black",
    "dark_blue",
    "dark_green",
    "red",
    "dark_red",
    "dark_purple",
    "gold",
    "yellow",
    "green",
    "dark_aqua",
    "aqua",
    "blue",
    "light_purple",
    "dark_gray",
    "gray"
]


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

        server_chat_re = re.compile(
            "INFO\]: <([A-Za-z0-9_]+)> (.*)$")
        server_join_re = re.compile(
            "INFO\]: ([A-Za-z0-9_]+) ?\[.*\] logged in")
        server_leave_re = re.compile(
            "INFO\]: ([A-Za-z0-9_]+) lost connection")

        while True:
            # Read from the process
            output_line = await self._subprocess.stdout.readline()

            if output_line:
                output_line = output_line.decode('utf-8')

                if self._config["enable_irc_bridge"]:
                    chat_match = server_chat_re.search(output_line)
                    if chat_match:
                        message = "<{}> {}".format(
                            chat_match.group(1), chat_match.group(2))
                        self.irc_send(message)

                    join_match = server_join_re.search(output_line)
                    if join_match:
                        message = "{} has joined Minecraft".format(
                            join_match.group(1))
                        self.irc_send(message)

                    leave_match = server_leave_re.search(output_line)
                    if leave_match:
                        message = "{} has left Minecraft".format(
                            leave_match.group(1))
                        self.irc_send(message)
            else:
                # Killed?
                # FIXME: This doesn't work half the time
                message = "\x02\x0304Server exited with code {}".format(
                    self._subprocess.returncode)
                self.irc_send(message)
                self._subprocess = None
                return

    def subprocess_kill(self):
        if self._subprocess:
            self._subprocess.kill()

    def irc_send(self, message):
        self._bottom.send('PRIVMSG',
                          target=self._config["irc_channel"],
                          message=message)

    def mc_send(self, irc_user, message):
        if not self._config["enable_irc_bridge"]:
            return
        if not self._subprocess:
            return

        if self._config["use_tellraw"]:
            fragments = []
            fragment = ''
            is_bold = False
            is_italics = False
            is_underline = False
            color = None

            def _append_now():
                if not fragment:
                    return

                fragment_struct = {
                    "text": fragment,
                    "bold": is_bold,
                    "underlined": is_underline,
                    "italic": is_italics
                }

                if color:
                    fragment_struct["color"] = color

                fragments.append(fragment_struct)

            i = 0
            while i < len(message):
                c = message[i]
                if c in string.printable:
                    fragment += c

                elif c == '\x02':
                    _append_now()
                    fragment = ''
                    is_bold = not is_bold
                elif c == '\x1D':
                    _append_now()
                    fragment = ''
                    is_italics = not is_italics
                elif c == '\x1F':
                    _append_now()
                    fragment = ''
                    is_underline = not is_underline

                elif c == '\x03':
                    _append_now()
                    fragment = ''

                    # Color
                    tmp_color = ''
                    i += 1
                    while message[i] in string.digits:
                        tmp_color += message[i]
                        i += 1
                    # Skip bg if given
                    if message[i] == ',':
                        i += 1
                        while message[i] in string.digits:
                            i += 1
                    i -= 1
                    tmp_color = int(tmp_color)
                    if tmp_color < 16:
                        color = IRC_TO_MC_NAME_LUT[tmp_color]

                elif c == '\x0F':
                    # Reset all
                    _append_now()
                    fragment = ''
                    is_bold = is_italics = is_underline = False
                    color = None

                i  += 1

            # Lingering bit
            _append_now()

            # Prefix
            fragments.insert(0, "[IRC] <{}> ".format(irc_user))

            json_str = json.dumps(fragments)
            formatted_message = "/tellraw @a " + json_str
        else:
            # Because of laziness, we don't translate formatting but do handle
            # colors
            colored_msg = ''
            i = 0
            while i < len(message):
                c = message[i]
                if c in string.printable:
                    colored_msg += c
                elif c == '\x03':
                    # Color
                    color = ''
                    i += 1
                    while message[i] in string.digits:
                        color += message[i]
                        i += 1
                    # Skip bg if given
                    if message[i] == ',':
                        i += 1
                        while message[i] in string.digits:
                            i += 1
                    i -= 1
                    color = int(color)
                    if color < 16:
                        colored_msg += IRC_TO_MC_HEX_LUT[color]
                elif c == '\x0F':
                    # Reset all
                    colored_msg += '§r'

                i += 1
            formatted_message = "/say <{}> {}".format(irc_user, colored_msg)

        formatted_message = (formatted_message + "\n").encode('utf-8')
        self._subprocess.stdin.write(formatted_message)

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
            self._bottom.send('PONG', message=message)

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
                # Not a command, send to MC
                self.mc_send(nick, message)
                return

            message = message.strip()
            fragments = message.split(maxsplit=2)
            if len(fragments) != 3:
                # Not a command, send to MC
                self.mc_send(nick, message)
                return

            # Command must start with "!<nick>" or "!!<nick>"
            if ((fragments[0] != ("!" + self._config["irc_nick"])) and
                    (fragments[0] != ("!!" + self._config["irc_nick"]))):
                # Forward to minecraft, not a command
                self.mc_send(nick, message)
                return

            is_special_cmd = fragments[0][:2] == "!!"

            # TODO: sig

            # Actual command
            real_command = fragments[2]

            if not is_special_cmd:
                # Command to forward to server
                if self._subprocess:
                    real_command = (real_command + "\n").encode('utf-8')
                    self._subprocess.stdin.write(real_command)
            else:
                # Command for us
                if real_command == "kill":
                    self.subprocess_kill()
                elif real_command == "launch":
                    if self._subprocess:
                        return
                    self._loop.create_task(self.subprocess_create())
                elif real_command == "status":
                    if not self._subprocess:
                        message = "Server not running"
                    else:
                        message = "Server running, PID {}".format(
                            self._subprocess.pid)

                    self.irc_send(message)
                elif real_command == "all-shutdown":
                    print("Shutting down!")
                    self.subprocess_kill()
                    self._bottom.send('QUIT', message=":( :( :(")
                    self._loop.stop()
                    return
                else:
                    # Bad command
                    message = "Unrecognized command: " + real_command
                    self.irc_send(message)

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
