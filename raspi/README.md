

# About this module

This Python script have following features

* Read UART and get message from TWELITE App Tag master node UART
* Send it to slack
* Send it to fluent-bit

## System Requirements
* Raspberry Pi Model B+
* TWELITE with App\_Tag parent firmware

# Memo

## Open TWELITE console via UART

> minicom -b 115200 -o -D /dev/ttyAMA0

Console operation of TWELITE
* https://mono-wireless.com/jp/products/TWE-APPS/App_Tag/interactive.html




