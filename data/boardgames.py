import sqlalchemy

from .db_session import SqlAlchemyBase


class Boardgames(SqlAlchemyBase):
    __tablename__ = 'boardgames'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    bgg_id = sqlalchemy.Column(sqlalchemy.Integer, unique=True)
    name = sqlalchemy.Column(sqlalchemy.String)
    year = sqlalchemy.Column(sqlalchemy.Integer)
    description = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    players = sqlalchemy.Column(sqlalchemy.String)
    playtime = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    rating = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    weight = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    users_rated = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    categories = sqlalchemy.Column(sqlalchemy.String)
    mechanics = sqlalchemy.Column(sqlalchemy.String)
    thumbnail = sqlalchemy.Column(sqlalchemy.String)
    image = sqlalchemy.Column(sqlalchemy.String)
    search_query = sqlalchemy.Column(sqlalchemy.String)
    timestamp = sqlalchemy.Column(sqlalchemy.Float)


    def __repr__(self):
        return f'<boardgame> {self.job}'