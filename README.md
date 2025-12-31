# 領収書 OCR 審査サンプル (CodexTest)

ローカル環境（Windows 11 向け想定）で領収書画像を OCR し、抽出結果を保存・一覧・承認できる簡易 Web アプリです。

## 機能
1. **申請登録**: 領収書画像をアップロードすると、日付/宛先/金額/登録番号を OCR で抽出し、申請者（初期値 XYY）、画像パスと一緒に SQLite DB へ保存。
2. **申請一覧**: これまでの申請をテーブルで表示。画像へのリンク付き。
3. **承認画面**: 申請ごとに領収書と抽出値を突合し、OK/NG とコメントを一括保存。最新の承認履歴を確認可能。

## セットアップ & 検証手順 (Windows 11 想定)
以下は **担当者 / 場所 / 実施内容 / 成功確認** を明記したステップバイステップ手順です。

1. **担当: 開発/検証者・場所: ローカル PC**
   - Python 3.11+ をインストール（公式サイト or Microsoft Store）。セットアップ時に `Add python.exe to PATH` をオン。
   - **確認:** PowerShell で `python --version` を実行し、バージョンが表示されれば OK。

2. **担当: 開発/検証者・場所: ローカル PC**
   - Tesseract OCR をインストール（例: [UB Mannheim 版](https://github.com/UB-Mannheim/tesseract/wiki)）。`Add to PATH` をオン、もしくはインストール先 (例: `C:\Program Files\Tesseract-OCR\tesseract.exe`) を控える。日本語データ `jpn` を含むパッケージを選択。
   - **確認:** PowerShell で `tesseract --version` を実行し、バージョンが表示されれば OK。

3. **担当: 開発/検証者・場所: リポジトリ直下**
   - 仮想環境と依存ライブラリをセットアップ。
   ```powershell
   cd path\to\CodexTest
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
   - **確認:** `python -m compileall app` でエラーが出なければ環境構築完了。

4. **担当: 開発/検証者・場所: リポジトリ直下**
   - (Tesseract を PATH に通していない場合のみ) 環境変数でパスを指定。
   ```powershell
   # 例: setx TESSERACT_CMD "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
   ```
   - **確認:** 再度 PowerShell を開き、`echo %TESSERACT_CMD%` で設定値が表示される。

5. **担当: 開発/検証者・場所: リポジトリ直下**
   - アプリを起動。
   ```powershell
   uvicorn app.main:app --reload
   ```
   - **確認:** ブラウザで `http://127.0.0.1:8000/health` にアクセスし `{"status":"ok"}` が返ればサーバー起動成功。

6. **担当: 管理者 (初期 admin)・場所: ブラウザ**
   - 既定の管理者でログイン: ユーザー名 `admin` / パスワード `admin123`。
   - **確認:** 右上のナビゲーションに「ログイン中: System Admin (admin)」と表示されれば認証成功。

7. **担当: 管理者・場所: ブラウザ**
   - `/auth/register` から一般ユーザーを登録（例: username=`user1`, 氏名=`Taro User`, password=`pass123`）。
   - **確認:** 登録後に「ユーザーを登録しました。」メッセージが出ること。

8. **担当: 一般ユーザー・場所: ブラウザ**
   - `/auth/login` で上記の一般ユーザーでログイン。
   - トップページから申請を作成（申請者名は自動でログインユーザー名が入ります）。領収書画像を選択して送信。
   - **確認:** 送信後 `/submissions?created=1` にリダイレクトされ、「申請を登録しました。」メッセージと新規行が表示されること。

9. **担当: 承認者（任意のログインユーザー）・場所: ブラウザ**
   - `/submissions` または `/approvals` の行/カードをクリックすると詳細ポップアップが表示されることを確認。右側に領収書画像、左側に申請情報と最新承認が並んでいること。
   - `/approvals` で OK/NG とコメントを入力し「一括で保存」を押下。
   - **確認:** 保存後の画面で最新承認欄に入力内容が反映されること。

## 使い方
- **申請 (機能1)**: トップページから申請者（初期値 XYY）と領収書画像を選択して送信。OCR 抽出結果と画像パスが DB に保存されます。
- **一覧 (機能2)**: `/submissions` で申請履歴を確認。画像は `/receipts/...` から直接参照可能。
- **承認 (機能3)**: `/approvals` で各申請の画像と抽出値を確認し、OK/NG とコメントを入力して一括保存。最新の承認結果がカード下部に表示されます。

## 補足
- データは `data/app.db` (SQLite) に保存されます。領収書画像は `data/receipts/` 配下へ保存されます。
- 既存 DB/画像を初期化したい場合は `data/app.db` と `data/receipts/*` を削除してください。
- OCR 精度は画像品質に依存します。読み取りに失敗した場合は承認画面でコメントを残して運用してください。
