# mokasenes
A handmade IoT system in Moka City.


# System Overview

* TWELITE の無線タグアプリを利用した、ワイヤレスでの温度計測
  * https://mono-wireless.com/jp/products/TWE-APPS/App_Tag/mode_ADT7410.html
* TWELITE と Raspberry Pi を UART で接続し、計測値を取り込み
* fluentd を用いて計測値を VPS に送信
* influxDB に蓄積
* Grafana で表示

* I2C 制御の LCD モジュール AQM1602 にメッセージ、温度を表示
  * http://akizukidenshi.com/catalog/g/gK-08896/

* GPIO を利用した LED によるイベント通知 (Lチカ)
* GPIO を利用したハットスイッチによる電源断

# Screenshot

https://github.com/ryu1k/mokasenes/blob/master/raspsense_output_sample.png


# ToDo
* システム全体の構成図の追加
* raspi と TWELITE, LCD 等の結線図、回路図の追加
* fluentd, influxDB, Grafana の設定情報の追加

