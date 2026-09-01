def test_social_account_token_encrypted_at_rest(register_and_login):
    from app.models import User, SocialAccount, Platform
    from app.database import SessionLocal

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    account = SocialAccount(
        owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="acc1",
        access_token="super-secret-access-token", refresh_token="super-secret-refresh-token",
    )
    db.add(account)
    db.commit()
    account_id = account.id
    db.close()

    # Читаем СЫРОЕ значение из БД в обход ORM-property — то, что реально
    # лежит на диске, не должно содержать исходный секрет открытым текстом
    db2 = SessionLocal()
    raw = db2.execute(
        __import__("sqlalchemy").text("SELECT access_token, refresh_token FROM social_accounts WHERE id = :id"),
        {"id": account_id},
    ).fetchone()
    assert "super-secret-access-token" not in raw[0]
    assert "super-secret-refresh-token" not in raw[1]

    # А через обычный ORM-доступ (property) значение расшифровывается прозрачно
    account2 = db2.query(SocialAccount).filter(SocialAccount.id == account_id).first()
    assert account2.access_token == "super-secret-access-token"
    assert account2.refresh_token == "super-secret-refresh-token"
    db2.close()
