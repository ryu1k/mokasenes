# mokasenes
Hand made IoT system on Moka City.


# System Overview

* TWELITE の無線タグアプリを利用した、ワイヤレスでの温度計測
  * https://mono-wireless.com/jp/products/TWE-APPS/App_Tag/mode_ADT7410.html
* TWELITE と Raspberry Pi を UART で接続し、計測値を取り込み
* fluentd を用いて計測値を VPS に送信
* influxDB に蓄積
* Grafana で表示

# Screenshot

https://github.com/ryu1k/mokasenes/blob/master/raspsense_output_sample.png

