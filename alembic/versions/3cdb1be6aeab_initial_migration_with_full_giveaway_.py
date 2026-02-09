"""Initial migration with full giveaway system

Revision ID: 3cdb1be6aeab
Revises: 
Create Date: 2025-12-12 13:35:30.196241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cdb1be6aeab'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаем таблицу users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('last_name', sa.String(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('is_owner', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)
    
    # Создаем таблицу giveaways
    op.create_table(
        'giveaways',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('creator_id', sa.Integer(), nullable=False),
        sa.Column('winners_count', sa.Integer(), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('prizes', sa.String(), nullable=True),
        sa.Column('participation_rules', sa.String(), nullable=True),
        sa.Column('image_file_id', sa.String(), nullable=True),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('target_chats', sa.JSON(), nullable=True),
        sa.Column('required_channels', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('announce_at', sa.DateTime(), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('announcement_text', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Создаем таблицу participations
    op.create_table(
        'participations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('is_winner', sa.Boolean(), nullable=True),
        sa.Column('participated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('participations')
    op.drop_table('giveaways')
    op.drop_index('ix_users_telegram_id', table_name='users')
    op.drop_table('users')
