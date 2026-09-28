import pytest
from sqlalchemy import select

from app.cli import add_user
from app.core.security import hash_password, verify_password
from app.db import begin_write
from app.dev_accounts import STUDENT_ACCOUNTS, seed_students
from app.models import User


def test_student_accounts_created_and_login_preserves_zero(env):
    with env.app.state.sessions() as db:
        begin_write(db)
        result = seed_students(db, environment="test")
        db.commit()
        assert len(result["created"]) == 6
        for student_id, name in STUDENT_ACCOUNTS:
            user = db.scalar(select(User).where(User.login_name == student_id))
            assert user.display_name == name
            assert user.password_hash != student_id
            assert verify_password(student_id, user.password_hash)
    for student_id, name in STUDENT_ACCOUNTS:
        response = env.client.post(
            "/api/v1/auth/login", json={"login_name": student_id, "password": student_id}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["login_name"] == student_id
        assert response.json()["user"]["display_name"] == name
    assert any(student_id.startswith("0") for student_id, _ in STUDENT_ACCOUNTS)


def test_seed_students_preserves_existing_passwords(env):
    with env.app.state.sessions() as db:
        begin_write(db)
        seed_students(db, environment="test")
        user = db.scalar(select(User).where(User.login_name == STUDENT_ACCOUNTS[0][0]))
        user.password_hash = hash_password("changed-password-for-test")
        saved_hash = user.password_hash
        db.commit()
        begin_write(db)
        result = seed_students(db, environment="test")
        db.commit()
        assert not result["created"] and len(result["existing"]) == 6
        assert (
            db.scalar(select(User).where(User.login_name == STUDENT_ACCOUNTS[0][0])).password_hash
            == saved_hash
        )


def test_student_seed_rejects_production(env):
    with env.app.state.sessions() as db:
        with pytest.raises(ValueError, match="生产环境"):
            seed_students(db, environment="production")
        assert db.scalar(select(User).where(User.login_name == STUDENT_ACCOUNTS[0][0])) is None


def test_student_seed_does_not_take_over_conflicting_account(env):
    with env.app.state.sessions() as db:
        begin_write(db)
        add_user(db, STUDENT_ACCOUNTS[-1][0], "已有的其他身份", "existing-password-123")
        db.commit()
        begin_write(db)
        with pytest.raises(ValueError, match="其他姓名"):
            seed_students(db, environment="test")
        db.rollback()
        assert db.scalar(select(User).where(User.login_name == STUDENT_ACCOUNTS[0][0])) is None


def test_normal_account_password_policy_is_not_weakened(env):
    with env.app.state.sessions() as db:
        with pytest.raises(ValueError, match="12"):
            add_user(db, "temporary", "额外测试账号", "123456789")
