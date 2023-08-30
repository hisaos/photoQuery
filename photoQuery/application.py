from flask import Flask, render_template, request, url_for
from PIL import Image
from io import BytesIO

import folium
import requests
import json
import datetime
import base64

application = Flask(__name__)

@application.route("/")
def root():
    # ここは写真投稿フォームを出す
    return render_template("form.html", cgi=url_for("photo_upload"))

@application.route("/photo_upload", methods=["POST"])
def photo_upload():
    latDeg, lonDeg, realEstatePriceData = photo2latlon(request.files["photo"])

    # 画像処理の時点でエラーを起こしていたらエラー画面を表示
    if latDeg == -1 and lonDeg == -1 and realEstatePriceData == {}:
        return render_template("error.html")
    
    # 画像のExifから出した緯度経度を入力してOpenStreetMapのベース地図を取得
    m = folium.Map(
        location=[latDeg, lonDeg],
        tiles = "OpenStreetMap",
        zoom_start = 15,
        width = 400,
        height = 400
    )

    # 国土地理院APIを呼んで洪水浸水深さのハザードマップを取得
    folium.raster_layers.TileLayer(
        tiles='https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_kuni_data/{z}/{x}/{y}.png',
        fmt='image/png',
        attr="Hazard map by the Geospatial Information Authority of Japan",
        tms=False,
        overlay=True,
        control=True,
        opacity=0.7
    ).add_to(m)

    # 2つの地図を重ね合わせる
    folium.LayerControl().add_to(m)

    # foliumでインタラクティブ地図としてブラウザに表示
    m.get_root().render()
    header = m.get_root().header.render()
    body_html = m.get_root().html.render()
    script = m.get_root().script.render()

    # 次のテンプレートに渡すために画像データをBase64にエンコード
    imgData = Image.open(request.files["photo"])
    buf = BytesIO()
    imgData.save(buf, format="jpeg")
    imgDataStr = base64.b64encode(buf.getvalue()).decode("ascii")

    return render_template("display.html", realEstatePriceData=realEstatePriceData, imgData=imgDataStr, header=header, body_html=body_html, script=script)

def photo2latlon(photo):
    # 入力された写真のExifから緯度経度データを抜き出す
    try:
        img = Image.open(photo)
        imgExif = img._getexif()
        latlon = imgExif[34853]	# 34853はExifの緯度経度を含むタグの番号
        latDeg = latlon[2][0] + latlon[2][1]/60.0 + latlon[2][2]/3600.0
        lonDeg = latlon[4][0] + latlon[4][1]/60.0 + latlon[4][2]/3600.0

        # API呼ぶ時に使うヘッダ
        headers = {
            "content-type": "application/json",
        }

        # 国土地理院APIを使って逆ジオコーディングしてmuniCdを取り出す
        revGeocodingUrl = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat={}&lon={}".format(latDeg, lonDeg)
        revGeocodingRes = requests.get(revGeocodingUrl, headers)
        revGeocodingResJson = json.loads(revGeocodingRes.text)
        muniCd = revGeocodingResJson["results"]["muniCd"]

        # muniCdを使って土地総合情報システムAPIを呼び、不動産取引価格情報を取得する
        fromYearQ, toYearQ = date2year_quarter()
        realEstatePriceUrl = "https://www.land.mlit.go.jp/webland/api/TradeListSearch?from={}&to={}&city={}".format(fromYearQ, toYearQ, muniCd)
        realEstatePriceRes = requests.get(realEstatePriceUrl, headers)
        realEstatePriceResJson = json.loads(realEstatePriceRes.text)

        # データの価格情報などがまとまっている部分だけ取り出す
        realEstatePriceData = realEstatePriceResJson["data"]
    
        return latDeg, lonDeg, realEstatePriceData
    except KeyError:
        # Exifにlatlonがない場合
        return -1, -1, {}

# 土地総合情報システムAPIに与える検索の始期・終期を現在時刻から求める
# 現在時刻から西暦年と四半期を示す5桁の数字を2つ返す
def date2year_quarter():
    # 現在時刻から西暦年と月を取り出す
    i_year = datetime.datetime.today().year
    i_month = datetime.datetime.today().month

    # その月がどの四半期かを表す数をi_quarterに格納する
    # 土地総合情報システムでは、1~3月=1、4~6月=2、7~10月=3、11~12月=4と>いう少し変則的な四半期の定義になっている
    if i_month >= 1 and i_month <= 3:
        i_quarter = 1
    elif i_month >= 4 and i_month <= 6:
        i_quarter = 2
    elif i_month >= 7 and i_month <= 10:
        i_quarter = 3
    else:
        i_quarter = 4

    # 土地総合情報システムの制限から、システム時計の時刻が2006年第1四半期以前になっていたら
    # 強制的にfromYearQ=20053, toYearQ=20054にする
    if i_year <= 2006 and i_quarter <= 1:
        return "20053", "20054"

    # 土地総合情報システムは現在時刻の2四半期前までのデータを返す
    # 検索の開始時期を現在時刻の2四半期前、終了時期を現在時刻の1四半期前にする
    if i_quarter == 1:
        fromYearQ = str(i_year-1) + "3"
        toYearQ = str(i_year-1) + "4"
    elif i_quarter == 2:
        fromYearQ = str(i_year-1) + "4"
        toYearQ = str(i_year) + "1"
    else:
        fromYearQ = str(i_year) + str(i_quarter-2)
        toYearQ = str(i_year) + str(i_quarter-1)

    return fromYearQ, toYearQ

if __name__ == "__main__":
    application.run(port=8080, debug=True)
