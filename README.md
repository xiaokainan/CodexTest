# 領収書 OCR 審査サンプル (CodexTest)

ローカル環境（Windows 11 向け想定）で領収書画像を OCR し、抽出結果を保存・一覧・承認できる簡易 Web アプリです。

## 機能
1. **申請登録**: 領収書画像をアップロードすると、日付/宛先/金額/登録番号を OCR で抽出し、申請者（初期値 XYY）、画像パスと一緒に SQLite DB へ保存。
2. **申請一覧**: これまでの申請をテーブルで表示。画像へのリンク付き。
3. **承認画面**: 申請ごとに領収書と抽出値を突合し、OK/NG とコメントを一括保存。最新の承認履歴を確認可能。

## セットアップ (Windows 11)
1. **Python を用意**
   - 公式サイトまたは Microsoft Store から Python 3.11+ をインストールし、`Add python.exe to PATH` を有効にする。
2. **Tesseract OCR をインストール**
   - [UB Mannheim 版](https://github.com/UB-Mannheim/tesseract/wiki) など Windows 用インストーラをダウンロードし、セットアップ。
   - セットアップ時に `Add to PATH` をオン、またはインストール先 (例: `C:\Program Files\Tesseract-OCR\tesseract.exe`) を控える。
   - 日本語対応のために `jpn` 言語データを含むパッケージを選択。
3. **依存パッケージをインストール**
   ```powershell
   cd path\to\CodexTest
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. **アプリを起動**
   ```powershell
   # Tesseract を PATH に追加していない場合は環境変数で指定
   # set TESSERACT_CMD="C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
   uvicorn app.main:app --reload
   ```
   - ブラウザで `http://127.0.0.1:8000/` にアクセス。

## 使い方
- **申請 (機能1)**: トップページから申請者（初期値 XYY）と領収書画像を選択して送信。OCR 抽出結果と画像パスが DB に保存されます。
- **一覧 (機能2)**: `/submissions` で申請履歴を確認。画像は `/receipts/...` から直接参照可能。
- **承認 (機能3)**: `/approvals` で各申請の画像と抽出値を確認し、OK/NG とコメントを入力して一括保存。最新の承認結果がカード下部に表示されます。

## 補足
- データは `data/app.db` (SQLite) に保存されます。領収書画像は `data/receipts/` 配下へ保存されます。
- 既存 DB/画像を初期化したい場合は `data/app.db` と `data/receipts/*` を削除してください。
- OCR 精度は画像品質に依存します。読み取りに失敗した場合は承認画面でコメントを残して運用してください。
