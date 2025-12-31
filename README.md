# 領収書 OCR 審査サンプル (CodexTest)

ローカル環境（Windows 11 向け想定）で領収書画像を OCR し、抽出結果を保存・一覧・承認できる簡易 Web アプリです。ログイン/申請/承認/ログアウトの操作ログを `data/logs/app.log` に記録します。

## 機能
1. **申請登録**: 領収書画像をアップロードすると、日付/宛先/金額/登録番号を OCR で抽出し、申請者（初期値 XYY）、画像パスと一緒に SQLite DB へ保存。
2. **申請一覧**: これまでの申請をテーブルで表示。画像へのリンク付き。
3. **承認画面**: 申請ごとに領収書と抽出値を突合し、OK/NG とコメントを一括保存。最新の承認履歴を確認可能。

## セットアップ (Windows 11, PowerShell)
以下は「誰がどこで何をどうやって実行し、成功をどう確認するか」を明示した手順です。

1. **前提を準備 (実行者: 開発者・場所: ローカル PC)**
   - [Python 3.11+](https://www.python.org/) をインストールし、セットアップ時に「Add python.exe to PATH」をオンにする。
   - [Tesseract OCR (UB Mannheim 版)](https://github.com/UB-Mannheim/tesseract/wiki) をインストールする。インストール先が PATH に入っていない場合は場所 (例: `C:\Program Files\Tesseract-OCR\tesseract.exe`) を控える。日本語対応のため `jpn` 言語データを含むパッケージを選択。

2. **コードを取得 (実行者: 開発者・場所: コード格納ディレクトリ)**
   ```powershell
   git clone <repository-url> CodexTest
   cd CodexTest
   ```

3. **仮想環境と依存関係 (実行者: 開発者・場所: `CodexTest` 直下)**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **環境変数を設定 (必要な人のみ・場所: PowerShell セッション)**
   - Tesseract を PATH に入れていない場合:
     ```powershell
     $env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
     ```
   - 管理者ユーザーの初期パスワードを変えたい場合:
     ```powershell
     $env:DEFAULT_ADMIN_PASSWORD="your-strong-password"
     ```
   - セッション暗号鍵を固定したい場合:
     ```powershell
     $env:SESSION_SECRET="random-hex-string"
     ```

5. **アプリを起動 (実行者: 開発者・場所: `CodexTest` 直下)**
   ```powershell
   uvicorn app.main:app --reload
   ```
   - ブラウザで `http://127.0.0.1:8000/` にアクセスし、画面が表示されれば起動成功。

6. **検証フロー (実行者: テスター・場所: ブラウザ)**
   1. **ログイン**: `/auth/login` で `admin` / `DEFAULT_ADMIN_PASSWORD` でサインイン。成功するとトップにリダイレクト。
   2. **申請登録**: トップで領収書画像をアップロードし送信。`/submissions` に登録された行が増えていれば成功。
   3. **承認**: `/approvals` で OK/NG を選び送信。直近の承認結果がカード下部に表示されれば成功。
   4. **ログアウト**: 画面のログアウトボタンを押す。再びトップへ戻り、ログイン画面が必要になる状態なら成功。
   5. **ログ確認**: 操作ログは `data/logs/app.log` に追記される。PowerShell で確認:
      ```powershell
      Get-Content data/logs/app.log -Tail 20
      ```
      - ログイン/ログアウト/申請/承認が「だれが (username)」「どのデバイス/IP」「いつ」「何をしたか」で記録されていることを確認。

7. **データの場所**
   - DB: `data/app.db` (SQLite)
   - 領収書画像: `data/receipts/`
   - 操作ログ: `data/logs/app.log`

## 使い方
- **申請 (機能1)**: トップページから申請者（初期値 XYY）と領収書画像を選択して送信。OCR 抽出結果と画像パスが DB に保存されます。
- **一覧 (機能2)**: `/submissions` で申請履歴を確認。画像は `/receipts/...` から直接参照可能。
- **承認 (機能3)**: `/approvals` で各申請の画像と抽出値を確認し、OK/NG とコメントを入力して一括保存。最新の承認結果がカード下部に表示されます。

## 補足
- データは `data/app.db` (SQLite) に保存されます。領収書画像は `data/receipts/` 配下へ保存されます。
- 既存 DB/画像を初期化したい場合は `data/app.db` と `data/receipts/*` を削除してください。
- OCR 精度は画像品質に依存します。読み取りに失敗した場合は承認画面でコメントを残して運用してください。
