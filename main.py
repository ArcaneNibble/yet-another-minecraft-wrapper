#!/usr/bin/env python3

import asyncio
import asyncio.subprocess
import binascii
import bottom
import ed25519
import errno
import json
import os
import re
import shutil
import string
import sys
import time


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
    _backup_task = None
    _backup_event = None
    _random = None
    _nonce = None

    def __init__(self, config, loop):
        self._config = config
        self._loop = loop

        self._backup_event = asyncio.Event(loop=loop)

        self._random = open("/dev/urandom", "rb")
        self.new_nonce()

    def new_nonce(self):
        self._nonce = self._random.read(16)

    async def backup_task(self):
        while True:
            await asyncio.sleep(self._config["backup_interval"])
            print("Backup...")

            self._subprocess.stdin.write(b'save-all\n')

            await self._backup_event.wait()
            print("Save done...")

            existing_backups = os.listdir("backups")
            # Filter out bogus (wrong length or not numbers)
            existing_backups = [
                x for x in existing_backups if len(x) == 14 and x.isdigit()]

            # We can sort them by converting them to numbers because we
            # purposely ordered the fields correctly
            existing_backups = sorted(existing_backups, key=int)
            # Keep only the specified number of backups
            # Delete one extra because we're just about to make one
            backups_to_delete = existing_backups[
                :-self._config["num_backups"] + 1]

            # Do this backup
            now_time = time.strftime("%Y%m%d%H%M%S", time.gmtime())
            shutil.copytree("world", "backups/" + now_time)
            print("Backup OK!")

            # Now delete the old backups
            for old_backup in backups_to_delete:
                print("Deleting old backup " + old_backup)
                shutil.rmtree("backups/" + old_backup)

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

        saving_re_1 = re.compile("Save complete.")
        saving_re_2 = re.compile("Saved the world")

        if self._config["backup_interval"] > 0:
            self._backup_task = self._loop.create_task(self.backup_task())

        while True:
            # Read from the process
            output_line = await self._subprocess.stdout.readline()

            if output_line:
                output_line = output_line.decode('utf-8')

                if (saving_re_1.search(output_line) or
                        saving_re_2.search(output_line)):
                    self._backup_event.set()
                    self._backup_event.clear()

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
                        self.irc_send(message, True)

                    leave_match = server_leave_re.search(output_line)
                    if leave_match:
                        message = "{} has left Minecraft".format(
                            leave_match.group(1))
                        self.irc_send(message, True)
            else:
                # Killed?
                # FIXME: This doesn't work half the time
                message = "\x02\x0304Server exited with code {}".format(
                    self._subprocess.returncode)
                self.irc_send(message)

                if self._backup_task:
                    self._backup_task.cancel()
                    self._backup_task = None

                self._subprocess = None
                return

    def subprocess_kill(self):
        if self._backup_task:
            self._backup_task.cancel()
            self._backup_task = None

        if self._subprocess:
            self._subprocess.kill()

    def irc_send(self, message, notice=False):
        cmd = 'PRIVMSG' if not notice else 'NOTICE'
        self._bottom.send(cmd,
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

                i += 1

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
        async def privmsg(nick, target, message, **kwargs):
            # User must be authorized
            if nick not in self._config["users"]:
                # Not a command, send to MC
                self.mc_send(nick, message)
                return

            fragments = message.strip().split(maxsplit=2)
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

            # Actual command
            real_command = fragments[2]

            if real_command == "nonce":
                nonce_text = binascii.hexlify(self._nonce).decode('ascii')
                self._bottom.send('PRIVMSG', message=nonce_text, target=nick)
                return

            # Sigcheck command
            if self._config["enable_sig_verify"]:
                # Signature must be this length
                if len(fragments[1]) != 86:
                    print("Signature invalid!")
                    return

                vk_enc = self._config["users"][nick]
                vk = ed25519.VerifyingKey(vk_enc, encoding='base64')

                bytes_to_sign = b'\x00' if not is_special_cmd else b'\x01'
                bytes_to_sign += self._nonce
                bytes_to_sign += real_command.encode('utf-8')

                try:
                    vk.verify(fragments[1], bytes_to_sign, encoding='base64')
                except ed25519.BadSignatureError:
                    print("Signature invalid!")
                    return

            self.new_nonce()

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

                    if self._backup_task:
                        self._backup_task.cancel()
                        self._backup_task = None

                    if self._subprocess:
                        self._subprocess.stdin.write(b"stop\n")
                        await self._subprocess.wait()
                    self._bottom.send('QUIT', message=":( :( :( ")
                    self._loop.stop()
                    return
                elif real_command[:7] == "taillog":
                    lines = 10
                    try:
                        lines = int(real_command[8:])
                    except ValueError:
                        pass

                    with open("logs/latest.log", "r") as f:
                        # FIXME: Ugly
                        lines = f.readlines()[-lines:]

                        for line in lines:
                            self.irc_send(line)
                else:
                    # Bad command
                    message = "Unrecognized command: " + real_command
                    self.irc_send(message)

        @self._bottom.on('JOIN')
        def irc_join(nick, user, host, **kwargs):
            if not self._config["enable_irc_bridge"]:
                return
            if not self._subprocess:
                return

            if nick == self._config["irc_nick"]:
                # Ourselves
                return

            message = "{} has joined IRC ({}!{}@{})".format(
                nick, nick, user, host)

            if self._config["use_tellraw"]:
                json_msg = json.dumps(["* " + message])
                formatted_message = "/tellraw @a " + json_msg
            else:
                formatted_message = "/say " + message

            formatted_message = (formatted_message + "\n").encode('utf-8')
            self._subprocess.stdin.write(formatted_message)

        @self._bottom.on('PART')
        def irc_part(nick, user, host, message, **kwargs):
            if not self._config["enable_irc_bridge"]:
                return
            if not self._subprocess:
                return

            if nick == self._config["irc_nick"]:
                # Ourselves
                return

            part_message = message
            message = "{} has left IRC".format(nick, nick, user)
            if part_message:
                message += " (" + part_message + ")"
            print(message)

            if self._config["use_tellraw"]:
                json_msg = json.dumps(["* " + message])
                formatted_message = "/tellraw @a " + json_msg
            else:
                formatted_message = "/say " + message

            formatted_message = (formatted_message + "\n").encode('utf-8')
            self._subprocess.stdin.write(formatted_message)
            print(formatted_message)

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

    # Ensure backup directory exists
    try:
        os.mkdir("backups")
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

    # Start event loop
    loop = asyncio.get_event_loop()
    serv = MinecraftServerWrapper(config, loop)
    loop.create_task(serv.start_wrapper())
    loop.run_forever()
    loop.close()

if __name__ == '__main__':
    main()
