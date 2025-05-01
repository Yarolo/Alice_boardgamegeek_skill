from boardgamegeek import BGGClient, BGGItemNotFoundError
import logging
from typing import Union, List, Dict, Any
import json
from datetime import datetime
import re
import html
from data import db_session
import os
import time
from sqlalchemy import create_engine, Column, Integer, String, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

if not (os.access('db/cache.db', os.F_OK)):
    db_session.global_init("db/cache.db")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boardgames.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

Base = declarative_base()


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


engine = create_engine('sqlite:///db/cache.db')
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
        self.cache_file = 'games_cache.json'
        self.partial_cache_file = 'partial_cache.json'
        self._load_caches()
        self.search_timeout = 4.5

    def _load_caches(self):
        try:
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}

        try:
            with open(self.partial_cache_file, 'r') as f:
                self.partial_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.partial_cache = {}

    def _save_caches(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)
        with open(self.partial_cache_file, 'w') as f:
            json.dump(self.partial_cache, f, indent=2)

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

    def find_game(self, game_name: str, use_cache: bool = True):
        start_time = time.time()
        game_name = game_name.strip().lower()
        if not game_name:
            raise ValueError("Название игры не может быть пустым")

        if use_cache and game_name in self.cache:
            cached_data = self.cache[game_name]
            if datetime.now().timestamp() - cached_data['timestamp'] < 86400:
                return cached_data['data']

        partial_key = f"partial_{game_name}"
        if use_cache and partial_key in self.partial_cache:
            partial_data = self.partial_cache[partial_key]
            if datetime.now().timestamp() - partial_data['timestamp'] < 86400:
                result = self._continue_from_partial_cache(game_name, partial_data, start_time)
                if result is not None:
                    return result

        try:
            game = self.bgg.game(game_name)
            if game and game.name.lower() == game_name:
                result = self._format_game_data(game)
                self._update_cache(game_name, result)
                self._save_to_db(result, game_name)
                return result
        except BGGItemNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Ошибка при поиске игры {game_name}: {str(e)}")
            if partial_key in self.partial_cache:
                del self.partial_cache[partial_key]

        try:
            return self._find_partial_matches(game_name, start_time)
        except Exception as e:
            if partial_key in self.partial_cache:
                del self.partial_cache[partial_key]
                self._save_caches()
            raise

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
                        self._update_cache(game_name, formatted_game)
                        return formatted_game

                processed_ids.append(item['id'])

                self.partial_cache[f"partial_{game_name}"] = {
                    'search_results': search_results,
                    'games': games,
                    'processed_ids': processed_ids,
                    'last_index': i + 1,
                    'timestamp': datetime.now().timestamp()
                }
                self._save_caches()

            except Exception as e:
                logger.warning(f"Ошибка при обработке игры {item['id']}: {str(e)}")
                continue

        if games:
            sorted_games = self._sort_games(games, game_name)
            self._update_cache(game_name, sorted_games)
            for game in sorted_games:
                self._save_to_db(game, game_name)
            if f"partial_{game_name}" in self.partial_cache:
                del self.partial_cache[f"partial_{game_name}"]
                self._save_caches()
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
            self.partial_cache[partial_key] = {
                'search_results': [{'id': item.id, 'name': item.name} for item in search_results],
                'games': [],
                'processed_ids': [],
                'last_index': 0,
                'timestamp': datetime.now().timestamp()
            }
            self._save_caches()

            result = self._continue_from_partial_cache(game_name, self.partial_cache[partial_key], start_time)
            if result is None and partial_key in self.partial_cache:
                if self.partial_cache[partial_key]['games']:
                    games = self.partial_cache[partial_key]['games']
                    sorted_games = self._sort_games(games, game_name)
                    for game in sorted_games:
                        self._save_to_db(game, game_name)
                    return sorted_games
            return result
        except Exception as e:
            logger.error(f"Ошибка при поиске частичных совпадений: {str(e)}")
            raise

    def _sort_games(self, games: List[Dict], game_name: str):
        return sorted(
            games,
            key=lambda x: (
                -x.get('users_rated', 0),
                -self._match_score(x['name'], game_name),
                -x.get('rating', 0)
            )
        )

    def _format_game_data(self, game):
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

    def _match_score(self, game_name: str, query: str):
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

    def _update_cache(self, game_name: str, data: Any):
        self.cache[game_name] = {
            'data': data,
            'timestamp': datetime.now().timestamp()
        }
        self._save_caches()

    def get_game_info(self, game_data: Union[Dict, List]) -> str:
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


def findgame(game_name: str):
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List]) -> str:
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