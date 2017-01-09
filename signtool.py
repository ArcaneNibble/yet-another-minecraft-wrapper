#!/usr/bin/env python3

import binascii
import ed25519
import sys


def usage():
    print("Usage: {} vk secret.bin".format(sys.argv[0]))
    print("       {} sign secret.bin nonce !|!! 'args'".format(sys.argv[0]))
    print("       {} verify vk sig nonce !|!! 'args'".format(sys.argv[0]))


def main():
    if len(sys.argv) < 3:
        usage()
        return

    if sys.argv[1] == "vk":
        # Generate verify key
        with open(sys.argv[2], "rb") as f:
            secret = f.read()
        if len(secret) != 32:
            print("ERROR: Secret must be 32 bytes!")
            return

        sk = ed25519.SigningKey(secret)
        vk = sk.get_verifying_key()
        print(vk.to_ascii(encoding='base64').decode('ascii'))

    elif sys.argv[1] == "sign":
        # Sign a command
        with open(sys.argv[2], "rb") as f:
            secret = f.read()
        if len(secret) != 32:
            print("ERROR: Secret must be 32 bytes!")
            return

        sk = ed25519.SigningKey(secret)

        is_special = sys.argv[4] == "!!"
        bytes_to_sign = b'\x00' if not is_special else b'\x01'

        # Nonce
        nonce = binascii.unhexlify(sys.argv[3])
        bytes_to_sign += nonce

        bytes_to_sign += sys.argv[5].encode('utf-8')
        sig = sk.sign(bytes_to_sign, encoding='base64').decode('ascii')
        print(sig)

    elif sys.argv[1] == "verify":
        # Verify a command
        vk = ed25519.VerifyingKey(sys.argv[2], encoding='base64')

        is_special = sys.argv[5] == "!!"
        bytes_to_sign = b'\x00' if not is_special else b'\x01'

        # Nonce
        nonce = binascii.unhexlify(sys.argv[4])
        bytes_to_sign += nonce

        bytes_to_sign += sys.argv[6].encode('utf-8')

        try:
            vk.verify(sys.argv[3], bytes_to_sign, encoding='base64')
            print("Signature OK!")
        except ed25519.BadSignatureError:
            print("Signature invalid!")

    else:
        usage()

if __name__ == '__main__':
    main()
