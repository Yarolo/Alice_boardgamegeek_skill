from boardgamegeek import BGGClient, BGGItemNotFoundError
import logging
from typing import Union, List, Dict, Any
import json
from datetime import datetime
import re
import html
import os
import time
from sqlalchemy import create_engine, Column, Integer, String, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


if not os.path.exists('db'):
    os.makedirs('db')

db_path = 'db/cache.db'
engine = create_engine(f'sqlite:///{db_path}')
Base = declarative_base()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boardgames.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CachedGame(Base):
    __tablename__ = 'cached_games'

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, index=True)
    name = Column(String, index=True)
    year = Column(Integer)
    description = Column(Text)
    players = Column(String)
    playtime = Column(String)
    rating = Column(Float)
    weight = Column(Float)
    users_rated = Column(Integer)
    categories = Column(String)
    mechanics = Column(String)
    thumbnail = Column(String)
    image = Column(String)
    search_query = Column(String, index=True)
    timestamp = Column(Float)


class PartialCache(Base):
    __tablename__ = 'partial_cache'

    id = Column(Integer, primary_key=True)
    search_query = Column(String, index=True)
    search_results = Column(Text)
    games = Column(Text)
    processed_ids = Column(Text)
    last_index = Column(Integer)
    timestamp = Column(Float)


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


class BoardGameFinder:
    def __init__(self):
        self.bgg = BGGClient(
            requests_per_minute=30,
            retries=3,
            retry_delay=5,
            timeout=30
        )
        self.search_timeout = 4.5

    def _get_cached_game(self, game_name: str) -> Union[Dict, None]:
        session = Session()
        try:
            cached = session.query(CachedGame).filter_by(search_query=game_name).order_by(
                CachedGame.timestamp.desc()).first()
            if cached and (datetime.now().timestamp() - cached.timestamp < 86400):
                return self._format_db_game_to_dict(cached)
            return None
        except Exception as e:
            logger.error(f"Error getting cached game: {str(e)}")
            return None
        finally:
            session.close()

    def _format_db_game_to_dict(self, db_game: CachedGame) -> Dict:
        return {
            'id': db_game.game_id,
            'name': db_game.name,
            'year': db_game.year,
            'description': db_game.description,
            'players': db_game.players,
            'playtime': db_game.playtime,
            'rating': db_game.rating,
            'weight': db_game.weight,
            'users_rated': db_game.users_rated,
            'categories': db_game.categories.split(',') if db_game.categories else [],
            'mechanics': db_game.mechanics.split(',') if db_game.mechanics else [],
            'thumbnail': db_game.thumbnail,
            'image': db_game.image,
            'last_updated': db_game.timestamp
        }

    def _get_partial_cache(self, game_name: str) -> Union[Dict, None]:
        session = Session()
        try:
            partial = session.query(PartialCache).filter_by(search_query=game_name).first()
            if partial and (datetime.now().timestamp() - partial.timestamp < 86400):
                return {
                    'search_results': json.loads(partial.search_results) if partial.search_results else [],
                    'games': json.loads(partial.games) if partial.games else [],
                    'processed_ids': json.loads(partial.processed_ids) if partial.processed_ids else [],
                    'last_index': partial.last_index,
                    'timestamp': partial.timestamp
                }
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in partial cache: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error getting partial cache: {str(e)}")
            return None
        finally:
            session.close()

    def _save_partial_cache(self, game_name: str, data: Dict):
        session = Session()
        try:
            existing = session.query(PartialCache).filter_by(search_query=game_name).first()
            if existing:
                existing.search_results = json.dumps(data['search_results'])
                existing.games = json.dumps(data['games'])
                existing.processed_ids = json.dumps(data['processed_ids'])
                existing.last_index = data['last_index']
                existing.timestamp = data['timestamp']
            else:
                new_cache = PartialCache(
                    search_query=game_name,
                    search_results=json.dumps(data['search_results']),
                    games=json.dumps(data['games']),
                    processed_ids=json.dumps(data['processed_ids']),
                    last_index=data['last_index'],
                    timestamp=data['timestamp']
                )
                session.add(new_cache)
            session.commit()
        except Exception as e:
            logger.error(f"Error saving partial cache: {str(e)}")
            session.rollback()
        finally:
            session.close()

    def _delete_partial_cache(self, game_name: str):
        session = Session()
        try:
            session.query(PartialCache).filter_by(search_query=game_name).delete()
            session.commit()
        except Exception as e:
            logger.error(f"Error deleting partial cache: {str(e)}")
            session.rollback()
        finally:
            session.close()

    def _save_to_db(self, game_data: Dict, search_query: str):
        session = Session()
        try:
            existing = session.query(CachedGame).filter_by(game_id=game_data['id'], search_query=search_query).first()
            if existing:
                existing.name = game_data['name']
                existing.year = game_data['year']
                existing.description = game_data['description']
                existing.players = game_data['players']
                existing.playtime = game_data['playtime']
                existing.rating = game_data['rating']
                existing.weight = game_data['weight']
                existing.users_rated = game_data['users_rated']
                existing.categories = ','.join(game_data['categories']) if game_data['categories'] else ''
                existing.mechanics = ','.join(game_data['mechanics']) if game_data['mechanics'] else ''
                existing.thumbnail = game_data['thumbnail']
                existing.image = game_data['image']
                existing.timestamp = datetime.now().timestamp()
            else:
                game = CachedGame(
                    game_id=game_data['id'],
                    name=game_data['name'],
                    year=game_data['year'],
                    description=game_data['description'],
                    players=game_data['players'],
                    playtime=game_data['playtime'],
                    rating=game_data['rating'],
                    weight=game_data['weight'],
                    users_rated=game_data['users_rated'],
                    categories=','.join(game_data['categories']) if game_data['categories'] else '',
                    mechanics=','.join(game_data['mechanics']) if game_data['mechanics'] else '',
                    thumbnail=game_data['thumbnail'],
                    image=game_data['image'],
                    search_query=search_query,
                    timestamp=datetime.now().timestamp()
                )
                session.add(game)
            session.commit()
        except Exception as e:
            logger.error(f"Error saving to database: {str(e)}")
            session.rollback()
        finally:
            session.close()

    def _format_description(self, description: str, max_length: int = 500) -> str:
        if not description or description == 'Описание отсутствует':
            return description
        description = html.unescape(re.sub(r'<[^>]+>', '', description))
        description = ' '.join(description.split())
        if len(description) > max_length:
            truncated = description[:max_length]
            last_punct = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
            if last_punct > 0:
                description = truncated[:last_punct + 1] + '..'
            else:
                description = truncated + '...'
        return description

    def find_game(self, game_name: str, use_cache: bool = True) -> Union[Dict, List[Dict], None]:
        start_time = time.time()
        game_name = game_name.strip().lower()
        if not game_name:
            raise ValueError("Название игры не может быть пустым")

        if use_cache:
            cached_data = self._get_cached_game(game_name)
            if cached_data:
                return cached_data

        partial_key = f"partial_{game_name}"
        if use_cache:
            partial_data = self._get_partial_cache(partial_key)
            if partial_data:
                result = self._continue_from_partial_cache(game_name, partial_data, start_time)
                if result is not None:
                    return result

        try:
            game = self.bgg.game(game_name)
            if game and game.name.lower() == game_name:
                result = self._format_game_data(game)
                self._save_to_db(result, game_name)
                return result
        except BGGItemNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Ошибка при поиске игры {game_name}: {str(e)}")
            self._delete_partial_cache(partial_key)

        try:
            return self._find_partial_matches(game_name, start_time)
        except Exception as e:
            self._delete_partial_cache(partial_key)
            raise ValueError(f"Не удалось найти игру: {str(e)}")

    def _continue_from_partial_cache(self, game_name: str, partial_data: dict, start_time: float):
        last_index = partial_data.get('last_index', 0)
        processed_ids = partial_data.get('processed_ids', [])
        search_results = partial_data.get('search_results', [])
        games = partial_data.get('games', [])

        for i in range(last_index, len(search_results)):
            if i >= 15:
                break

            if time.time() - start_time > self.search_timeout:
                logger.info(f"Timeout reached during partial cache processing for {game_name}")
                if games:
                    sorted_games = self._sort_games(games, game_name)
                    for game in sorted_games:
                        self._save_to_db(game, game_name)
                    return sorted_games
                return None

            item = search_results[i]
            if item['id'] in processed_ids:
                continue

            try:
                game = self.bgg.game(game_id=item['id'])
                if getattr(game, 'users_rated', 0) > 0:
                    formatted_game = self._format_game_data(game)
                    games.append(formatted_game)
                    self._save_to_db(formatted_game, game_name)

                    if game.name.lower() == game_name:
                        self._delete_partial_cache(f"partial_{game_name}")
                        return formatted_game

                processed_ids.append(item['id'])

                self._save_partial_cache(f"partial_{game_name}", {
                    'search_results': search_results,
                    'games': games,
                    'processed_ids': processed_ids,
                    'last_index': i + 1,
                    'timestamp': datetime.now().timestamp()
                })

            except Exception as e:
                logger.warning(f"Ошибка при обработке игры {item['id']}: {str(e)}")
                continue

        if games:
            sorted_games = self._sort_games(games, game_name)
            for game in sorted_games:
                self._save_to_db(game, game_name)
            self._delete_partial_cache(f"partial_{game_name}")
            return sorted_games

        return None

    def _find_partial_matches(self, game_name: str, start_time: float):
        try:
            if time.time() - start_time > self.search_timeout:
                logger.info(f"Timeout reached before starting partial search for {game_name}")
                return None

            search_results = self.bgg.search(game_name)
            if not search_results:
                raise ValueError(f"Игра '{game_name}' не найдена")

            partial_key = f"partial_{game_name}"
            self._save_partial_cache(partial_key, {
                'search_results': [{'id': item.id, 'name': item.name} for item in search_results],
                'games': [],
                'processed_ids': [],
                'last_index': 0,
                'timestamp': datetime.now().timestamp()
            })

            partial_data = self._get_partial_cache(partial_key)
            if not partial_data:
                raise ValueError("Не удалось сохранить частичный кэш")

            result = self._continue_from_partial_cache(game_name, partial_data, start_time)
            if result is None:
                partial_data = self._get_partial_cache(partial_key)
                if partial_data and partial_data.get('games'):
                    sorted_games = self._sort_games(partial_data['games'], game_name)
                    for game in sorted_games:
                        self._save_to_db(game, game_name)
                    return sorted_games
            return result
        except Exception as e:
            logger.error(f"Ошибка при поиске частичных совпадений: {str(e)}")
            self._delete_partial_cache(f"partial_{game_name}")
            raise ValueError(f"Ошибка при поиске игр: {str(e)}")

    def _sort_games(self, games: List[Dict], game_name: str) -> List[Dict]:
        return sorted(
            games,
            key=lambda x: (
                -x.get('users_rated', 0),
                -self._match_score(x['name'], game_name),
                -x.get('rating', 0)
            )
        )

    def _format_game_data(self, game) -> Dict:
        return {
            'id': game.id,
            'name': game.name,
            'year': game.year,
            'description': self._format_description(getattr(game, 'description', 'Описание отсутствует')),
            'players': f"{game.min_players}-{game.max_players}" if hasattr(game, 'min_players') else "N/A",
            'playtime': f"{game.playing_time} мин" if hasattr(game, 'playing_time') else "N/A",
            'rating': getattr(game, 'rating_average', 0),
            'weight': getattr(game, 'rating_average_weight', 0),
            'users_rated': getattr(game, 'users_rated', 0),
            'categories': getattr(game, 'categories', []),
            'mechanics': getattr(game, 'mechanics', []),
            'thumbnail': getattr(game, 'thumbnail', None),
            'image': getattr(game, 'image', None),
            'last_updated': datetime.now().timestamp()
        }

    def _match_score(self, game_name: str, query: str) -> float:
        game_name = game_name.lower()
        query = query.lower()

        if game_name == query:
            return 1.0

        if query in game_name:
            return 0.9

        query_words = set(query.split())
        game_words = set(game_name.split())
        common_words = query_words & game_words

        return len(common_words) / max(len(query_words), 1)

    def get_game_info(self, game_data: Union[Dict, List[Dict]]) -> str:
        if isinstance(game_data, list):
            return self._format_multiple_games(game_data)
        return self._format_single_game(game_data)

    def _format_single_game(self, game: Dict[str, Any]) -> str:
        weight = game.get('weight', 0)
        if weight == 0:
            weight_str = "Не указана"
        elif weight < 2:
            weight_str = f"{weight:.1f} (Лёгкая)"
        elif weight < 3.5:
            weight_str = f"{weight:.1f} (Средняя)"
        else:
            weight_str = f"{weight:.1f} (Сложная)"

        info = [
            f"🎲 {game['name']} ({game['year']})",
            f"👥 Игроков: {game['players']}",
            f"⏱ Время игры: {game['playtime']}",
            f"⭐ Рейтинг: {game['rating']:.2f} (на основе {game.get('users_rated', 0)} оценок)",
            f"🧠 Сложность: {weight_str}",
            f"📝 Описание: {game['description']}",
            f"🏷 Категории: {', '.join(game['categories'][:5])}" if game['categories'] else "",
            f"⚙ Механики: {', '.join(game['mechanics'][:5])}" if game['mechanics'] else ""
        ]
        return '\n'.join(filter(None, info))

    def _format_multiple_games(self, games: List[Dict[str, Any]]) -> str:
        if not games:
            return "Игры не найдены"

        games_list = []
        for i, game in enumerate(games[:5], 1):
            weight = game.get('weight', 0)
            weight_str = f"{weight:.1f}" if weight > 0 else "?"

            games_list.append(
                f"{i}. {game['name']} ({game['year']}) - ⭐ {game['rating']:.1f} "
                f"(🏋️ {weight_str}, 👥 {game['players']}, ⏱ {game['playtime']})"
            )

        return ("Найдено несколько игр. Уточните запрос:\n\n" +
                '\n'.join(games_list) +
                "\n\nПоказано топ-5 из найденных игр.")


finder = BoardGameFinder()


def findgame(game_name: str) -> Union[Dict, List[Dict], None]:
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List[Dict]]) -> str:
    return finder.get_game_info(game_data)


if __name__ == '__main__':
    try:
        print("=== Точный поиск ===")
        monopoly = findgame("Monopoly")
        print(game_base_info(monopoly))

        print("\n=== Частичный поиск ===")
        card_games = findgame("Card")
        print(game_base_info(card_games))

        print("\n=== Тест кэширования ===")
        start_time = datetime.now()
        cached_result = findgame("Monopoly")
        print(f"Время выполнения (с кэшем): {datetime.now() - start_time}")

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
