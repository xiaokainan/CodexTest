# CodexTest

Flask 製の領収書ワークフローです。領収書画像をアップロードすると OCR で日付・宛先・金額・登録番号を抽出し、申請データとして保存します。申請一覧と承認チェック画面を備えています。

## セットアップ

1. 依存関係のインストール
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. OCR のために [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) をローカルにインストールしてください（`tesseract` コマンドが必要です）。インストールしていない場合もアプリは動作しますが、抽出結果は空になる可能性があります。
3. 開発サーバーを起動
   ```bash
   flask --app app run --debug
   ```

## 主な画面
- **申請 ( /submit )**: 領収書画像をアップロードし、OCR 抽出と申請登録を実行します。初期の申請者名は `XYY` です。
- **申請一覧 ( /applications )**: 登録済みの申請を確認できます。抽出テキストや画像へのリンクを含みます。
- **承認 ( /approvals )**: 申請ごとに画像と抽出結果を再確認し、OK/NG とメモを更新できます。

## データベース
SQLite を使用します。データは `instance/receipts.db` に保存されます。`uploads/` 配下にアップロードした領収書画像を保存します。
