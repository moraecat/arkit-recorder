# ARKit Recorder

[한국어](README.md) | [English](README.en.md) | **日本語**

<img width="1440" height="1440" alt="arkit-recorder" src="https://github.com/user-attachments/assets/68c2aec8-ee43-4c9c-83ed-8b188bcdcda6" />

iPhoneのフェイストラッキング(iFacialMocap)の**信号そのものを
録画し、iPhoneなしで再生送信**できる常駐型UDPプロキシです。

iFacialMocapプロトコルのパケットを無加工のまま記録し、元のタイミングで再送する
方式のため、特定のソフトに依存しません — **iFacialMocapプロトコルを受信できる
どのツールでも再生可能**です([Warudo](https://warudo.app)、VSeeFace、VNyan、
iFacialMocap PCソフトなど)。配信中の離席ループや繰り返しの表情演技のために
作られました。

## 仕組み

```
[パススルー / 録画]
iPhoneアプリ --UDP--> ARKit Recorder :49983 --そのまま転送--> 受信アプリ :49984
                          |
                          +--> (録画中) clips/名前.jsonl に無劣化記録

[再生 / スクラブ]
クリップ --> ARKit Recorder --元のタイミングで--> 受信アプリ :49984
             (この間ライブは遮断、終了時はクロスフェードで復帰)
```

iFacialMocapの受信側は純粋なUDP受信のため、送信元がiPhoneか本プログラムかを
区別しません。パケットを解析・加工せずそのまま保存するので再生の忠実度は100%、
52個のARKitブレンドシェイプ + 頭の位置/回転 + 視線がすべて保存されます。

## 機能

- **パススルー**: 平常時は透過プロキシ (iPhone → 受信アプリ)
- **録画**: ボタンを押した瞬間に停止、無劣化JSONL保存、リアルタイム波形表示
- **再生**: 区間(トリム)再生/ループ、再生中の区間リアルタイム変更、
  開始/ループ/復帰クロスフェード
- **タイムライン**: アクティビティ・ブレンドシェイプ(52種)カーブ、スクラブ
  (ドラッグにアバターがリアルタイムで追従)、非破壊トリミング
- **一時停止**: タイムラインをクリック/リリース = そのフレームで固定
  (キープアライブで受信側のタイムアウトを防止)、トグルボタンで表示/操作
- **クリップ管理**: 名前変更/削除/長さ表示、設定GUI (ポート・クロスフェード即時適用)

## 使い方

### 初回設定

受信アプリのiFacialMocap受信ポートを **49983 → 49984に変更**してください
(例: WarudoのiFacialMocap Receiverアセットの Port プロパティ)。iPhoneアプリの
設定(PCのIP入力)はそのままで構いません。受信アプリのポートを変更できない場合は、
本プログラムの設定で転送ポートを受信アプリに合わせることもできます
(受信ポート49983と異なっていれば動作します)。

### 実行

配布された `arkit-recorder.exe` を実行するか:

```
pip install -r requirements.txt
python main.py
```

初回起動時、exe(または main.py)の隣に `config.json` と `clips/` フォルダが
作成されます。本プログラムが起動していない間はトラッキングが受信アプリに
届かないため、配信中は常時起動が前提です。

## 動作環境

- Windows PC (exeは単体で動作 — インストール不要)
- ARKitフェイストラッキング対応iPhone + iFacialMocapプロトコル送信アプリ
  (iFacialMocap、FaceMotion3Dなど)
- iFacialMocapプロトコル受信アプリ (Warudo、VSeeFace、VNyanなど)

## 開発 (ソースから実行)

Python 3.11+ と PySide6 が必要です (`pip install -r requirements.txt`)。
コアロジックは標準ライブラリのみを使用しています。

```
python main.py                                                   # 実行
pyinstaller --onefile --windowed --name arkit-recorder main.py   # exeビルド
```

## ライセンス

[MIT](LICENSE)
