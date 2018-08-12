# mokasenes
A handmade IoT system in Moka City.


# System Overview

* TWELITE の無線タグアプリを利用した、ワイヤレスでの温度計測
  * https://mono-wireless.com/jp/products/TWE-APPS/App_Tag/mode_ADT7410.html
* TWELITE-DIP と Raspberry Pi を UART で接続し、計測値を取り込み
* fluentd を用いて計測値を VPS に送信
* InfluxDB に蓄積
* Grafana で表示

* I2C 制御の LCD モジュール AQM1602 にメッセージ、温度を表示
  * http://akizukidenshi.com/catalog/g/gK-08896/

* GPIO を利用した LED によるイベント通知 (Lチカ)
* GPIO を利用したハットスイッチによる電源断

# Data flow

* ADT7410
  * Task:
    * Temperature measurement
  * Output:
    * I2C -> TWELITE-DIP (App_Tag child)

* TWELITE-DIP (App_Tag child)
  * Task:
    * Control ADT7410 and wireless transfer of data
  * Output:
    * IEEE 802.15.4 Wireless -> TWELITE-DIP (App_Tag parent)

* TWELITE-DIP (App_Tag parent)
  * Task:
    * Wireless receiver  
  * Output:
    * UART -> Raspberry Pi

* Raspberry Pi
  * Task:
    * Process raw data and distribute it to utilize.
  * Output:
    * Display value in LCD
    * Slack incoming webhook API -> Slack
    * TCP -> td-agent-bit (fluentd lightwaight agent)

* Slack
  * Task:
    * Notify event to human.
  * Output:
    * mention -> Notify High temperature, low battery voltate and so on.

* td-agent-bit
  * Task:
    * forwad data to td-agent
  * Output:
    * TCP (Fluentd Forward Protocol) -> td-agent (On VPS)

* td-agent
  * Task:
    * Gather data and put it to storage.
  * Output:
    * td-agent InfluxDB driver -> InfluxDB
    * stdout (to logfile) -> keep raw log

* InfluxDB
  * Task:
    * Store data
  * Output:
    * database -> Will be used by Grafana

* Grafana
  * Task:
    * View data and generate Event
  * Output:
    * Web UI -> Display data via Web Browser
    * Slack incoming webhook API -> Slack (Event trigger of Grafana)


# Screenshots

* Raspberry Pi + TWELITE-DIP の親ノード, LCD, センサ(子)ノード + ADT7410
  * https://github.com/ryu1k/mokasenes/blob/master/system_overview_photo.jpg
    * 左下の小さいチップ : ADT7410 温度センサ
    * ADT7410 に繋っているモジュール : TWELITE-DIP のセンサ(子)ノード
    * 上 : Raspberry Pi Model
    * 右下のブレッドボード : AQM1602 LCD, TWELITE-DIP の親ノード
* Grafana のスクリーンショット
  * https://github.com/ryu1k/mokasenes/blob/master/raspsense_output_sample.png

# ToDo

* システム全体の構成図の追加
* raspi と TWELITE, LCD 等の結線図、回路図の追加
* fluentd, InfluxDB, Grafana の設定情報の追加

