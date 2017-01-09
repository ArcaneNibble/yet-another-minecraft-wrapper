#!/usr/bin/env python3

import json
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: {} config.json".format(sys.argv[0]))
        return

    # Load config
    with open(sys.argv[1], 'r') as f:
        config = json.load(f)
    print(config)

if __name__ == '__main__':
    main()
