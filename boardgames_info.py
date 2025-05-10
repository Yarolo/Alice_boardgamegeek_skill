from boardgamegeek import BGGClient, BGGItemNotFoundError
import logging
from typing import Union, List, Dict, Any, Optional
from datetime import datetime
import re
import html
import os
import time
import random
from random import choice
from deep_translator import GoogleTranslator
from data import db_session
from data.boardgames import Boardgames

# Настройка базы данных
if not os.path.exists('db'):
    os.makedirs('db')
db_session.global_init("db/cache.db")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boardgames.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Настройка перевода
class GameTranslator:
    def __init__(self):
        self.translator = GoogleTranslator(source='auto', target='ru')
        self.cache = {}

    def translate(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text
        if text in self.cache:
            return self.cache[text]
        try:
            result = self.translator.translate(text)
            self.cache[text] = result
            return result
        except Exception as e:
            logger.error(f"Ошибка перевода текста '{text}': {str(e)}")
            return text


class BoardGameFinder:
    def __init__(self):
        self.bgg = BGGClient(
            requests_per_minute=1000,
            retries=3,
            retry_delay=5,
            timeout=30
        )
        self.translator = GameTranslator()
        self.skipped_results = 0
        self.search_timeout = 4.5
        self.min_users_rated = 50  # Минимальное количество оценок для популярной игры

    def _format_db_game_to_dict(self, db_game: Boardgames) -> Dict:
        """Конвертирует объект игры из БД в словарь с переведенными полями"""
        return {
            'id': db_game.bgg_id,
            'name': db_game.name,
            'year': db_game.year,
            'description': self.translator.translate(db_game.description),
            'players': db_game.players,
            'playtime': db_game.playtime,
            'rating': db_game.rating,
            'weight': db_game.weight,
            'users_rated': db_game.users_rated,
            'categories': [self.translator.translate(cat) for cat in
                           db_game.categories.split(',')] if db_game.categories else [],
            'mechanics': [self.translator.translate(mech) for mech in
                          db_game.mechanics.split(',')] if db_game.mechanics else [],
            'thumbnail': db_game.thumbnail,
            'image': db_game.image,
        }

    def _save_to_db(self, game_data: Dict, search_query: str, end_of_search: bool):
        """Сохраняет данные игры в БД с обработкой ошибок"""
        db_sess = db_session.create_session()
        try:
            game = Boardgames(
                bgg_id=game_data['id'],
                name=game_data['name'],  # Сохраняем оригинальное название
                year=game_data['year'],
                description=game_data['description'],  # Сохраняем оригинальное описание
                players=game_data['players'],
                playtime=game_data['playtime'],
                rating=game_data['rating'],
                weight=game_data['weight'],
                users_rated=game_data['users_rated'],
                categories=','.join(game_data['categories']) if game_data['categories'] else '',
                mechanics=','.join(game_data['mechanics']) if game_data['mechanics'] else '',
                thumbnail=game_data['thumbnail'],
                image=game_data['image'],
                search_query=search_query.lower(),
                search_time=datetime.now(),
                end_of_search=end_of_search
            )
            db_sess.add(game)
            db_sess.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения в БД: {str(e)}")
            db_sess.rollback()
        finally:
            db_sess.close()

    def _format_description(self, description: str, max_length: int = 500) -> str:
        """Очищает и сокращает описание игры"""
        if not description or description == 'No description available':
            return self.translator.translate("Описание отсутствует")
        description = html.unescape(re.sub(r'<[^>]+>', '', description))
        description = ' '.join(description.split())
        if len(description) > max_length:
            truncated = description[:max_length]
            last_punct = max(
                truncated.rfind('.'),
                truncated.rfind('!'),
                truncated.rfind('?'),
                truncated.rfind('\n')
            )
            description = truncated[:last_punct + 1] + '..' if last_punct > 0 else truncated + '...'
        return description

    def find_game(self, game_name: str, use_cache: bool = True) -> Union[Dict, List[Dict], str, None]:
        """Находит игру по названию с кэшированием и запасной логикой"""
        start_time = time.time()
        game_name = game_name.strip().lower()
        if not game_name:
            raise ValueError("Название игры не может быть пустым")
        # Сначала проверяем кэш
        if use_cache:
            cached_result = self._check_cache(game_name, start_time)
            if cached_result:
                return cached_result
        # Пробуем точное совпадение
        try:
            game = self.bgg.game(game_name)
            if game and game.name.lower() == game_name and game.users_rated >= self.min_users_rated:
                result = self._format_game_data(game)
                self._save_to_db(result, game_name, True)
                return result
        except BGGItemNotFoundError as e:
            logger.info(f"Точное совпадение не найдено для {game_name}: {str(e)}")
        # Запасной вариант - поиск
        return self._search_fallback(game_name, start_time)

    def _check_cache(self, game_name: str, start_time) -> Union[Dict, List[Dict], None]:
        """Проверяет кэш БД на наличие результатов"""
        db_sess = db_session.create_session()
        try:
            db_search_results = db_sess.query(Boardgames).filter(
                Boardgames.search_query == game_name
            ).order_by(Boardgames.users_rated.desc()).all()
            logging.info(f'db_search_results on "{game_name}": {db_search_results}')
            if time.time() - start_time > self.search_timeout - 2.0:
                return [{}]
            if db_search_results:
                if len(db_search_results) == 1 and db_search_results[0].end_of_search:
                    return self._format_db_game_to_dict(db_search_results[0])
                if len(db_search_results) > 1 and any(i.end_of_search for i in db_search_results):
                    games = [self._format_db_game_to_dict(i) for i in db_search_results]
                    result = []
                    for i in games:
                        if i not in result:
                            result.append(i)
                    return result
        finally:
            db_sess.close()
        return None

    def _search_fallback(self, game_name: str, start_time: float) -> Union[List[Dict], Dict]:
        """Альтернативный поиск, когда точное совпадение не найдено"""
        search_results = self.bgg.search(game_name)
        if not search_results:
            raise ValueError(f"Игра '{game_name}' не найдена")
        if len(search_results) < 10:
            raise ValueError(f"Игра '{game_name}' не найдена")
        db_sess = db_session.create_session()
        try:
            existing_count = db_sess.query(Boardgames).filter(
                Boardgames.search_query == game_name
            ).count()
            processed = existing_count
            for item in search_results[existing_count + self.skipped_results:]:
                if time.time() - start_time > self.search_timeout - 2.5:
                    break
                try:
                    game = self.bgg.game(game_id=item.id)
                    if game.users_rated >= self.min_users_rated:
                        formatted_game = self._format_game_data(game)
                        is_last = processed == len(search_results) - 2 or processed >= 15
                        self._save_to_db(formatted_game, game_name, is_last)
                        processed += 1
                except Exception as e:
                    logger.warning(f"Ошибка обработки игры {item.id}: {str(e)}")
                    self.skipped_results += 1
            # Возвращаем то, что есть в кэше
            return [{}]
        finally:
            db_sess.close()

    def _format_game_data(self, game) -> Dict:
        """Форматирует сырые данные игры из BGG API"""
        players = f"{game.min_players}-{game.max_players}" if hasattr(game, 'min_players') else "N/A"
        playtime = f"{game.playing_time} мин" if hasattr(game, 'playing_time') else "N/A"
        return {
            'id': game.id,
            'name': game.name,
            'year': game.year,
            'description': self._format_description(getattr(game, 'description', 'No description available')),
            'players': players,
            'playtime': playtime,
            'rating': round(getattr(game, 'rating_average', 0), 2),
            'weight': round(getattr(game, 'rating_average_weight', 0), 2),
            'users_rated': getattr(game, 'users_rated', 0),
            'categories': getattr(game, 'categories', []),
            'mechanics': getattr(game, 'mechanics', []),
            'thumbnail': getattr(game, 'thumbnail', None),
            'image': getattr(game, 'image', None),
        }

    def _match_score(self, game_name: str, query: str) -> float:
        """Вычисляет степень соответствия названия игры поисковому запросу"""
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
        """Форматирует данные игры в удобочитаемую строку"""
        if isinstance(game_data, list):
            return self._format_multiple_games(game_data)
        return self._format_single_game(game_data)

    def _format_single_game(self, game: Dict[str, Any]) -> str:
        """Форматирует информацию об одной игре"""
        weight = game.get('weight', 0)
        if weight == 0:
            weight_str = self.translator.translate("Не указана")
        elif weight < 2:
            weight_str = f"{weight:.1f} ({self.translator.translate('Легкая')})"
        elif weight < 3.5:
            weight_str = f"{weight:.1f} ({self.translator.translate('Средняя')})"
        else:
            weight_str = f"{weight:.1f} ({self.translator.translate('Тяжелая')})"
        info = [
            f"🎲 {game['name']} ({game['year']})",
            f"👥 Игроков: {game['players']}",
            f"⏱ Время игры: {game['playtime']}",
            f"⭐ Рейтинг: {game['rating']:.2f} "
            f"(на основе {game.get('users_rated', 0)} оценок)",
            f"🧠 Сложность: {weight_str}",
            f"📝 Описание: {self.translator.translate(game['description'])}",
            f"🏷 Категории: {', '.join(game['categories'][:5])}"
            if game.get('categories') else "",
            f"⚙ Механики: {', '.join(game['mechanics'][:5])}"
            if game.get('mechanics') else ""
        ]
        return '\n'.join(filter(None, info))

    def _format_multiple_games(self, games: List[Dict[str, Any]]) -> str:
        """Форматирует несколько игр в список для сравнения"""
        if not games or not games[0]:
            return "Поиск в процессе"
        games_list = []
        for i, game in enumerate(games[:5], 1):
            weight = game.get('weight', 0)
            weight_str = f"{weight:.1f}" if weight > 0 else "?"
            games_list.append(
                f"{i}. {game['name']} ({game['year']}) - ⭐ {game['rating']:.1f} "
                f"(🏋️ {weight_str}, 👥 {game['players']}, ⏱ {game['playtime']})"
            )
        return ("Найдено несколько игр. Уточните запрос:\n" + '\n'.join(games_list) +
                f"\n\nПоказаны топ-5 из найденных игр.")

    def get_random_game_names(self, count: int = 5) -> List[str]:
        """Возвращает список случайных популярных названий игр из кэша"""
        db_sess = db_session.create_session()
        try:
            games = db_sess.query(Boardgames.name).filter(
                Boardgames.users_rated >= self.min_users_rated
            ).order_by(Boardgames.rating.desc()).limit(100).all()

            if not games:
                return []

            sample_size = min(count, len(games))
            return [name for (name,) in random.sample(games, sample_size)]
        except Exception as e:
            logger.error(f"Ошибка получения случайных названий игр: {str(e)}")
            return []
        finally:
            db_sess.close()

    def get_random_game(self,
                        min_rating: float = 0,
                        min_players: Optional[int] = None,
                        max_players: Optional[int] = None) -> Dict:
        """Получает случайную игру по критериям"""
        db_sess = db_session.create_session()
        try:
            query = db_sess.query(Boardgames).filter(
                Boardgames.rating >= min_rating,
                Boardgames.users_rated >= self.min_users_rated
            )
            if min_players is not None:
                query = query.filter(Boardgames.players.contains(f"{min_players}-"))
            if max_players is not None:
                query = query.filter(Boardgames.players.contains(f"-{max_players}"))
            games = query.all()
            return self._format_db_game_to_dict(choice(games)) if games else {}
        except Exception as e:
            logger.error(f"Ошибка получения случайной игры: {str(e)}")
            return {}
        finally:
            db_sess.close()

    def get_recommendations(self,
                            liked_categories: List[str] = [],
                            disliked_categories: List[str] = [],
                            min_rating: float = 7.0,
                            limit: int = 5) -> List[Dict]:
        """Получает рекомендации игр на основе любимых/нелюбимых категорий"""
        db_sess = db_session.create_session()
        try:
            query = db_sess.query(Boardgames).filter(
                Boardgames.rating >= min_rating,
                Boardgames.users_rated >= self.min_users_rated
            )
            liked_translated = [self.translator.translate(cat) for cat in liked_categories]
            disliked_translated = [self.translator.translate(cat) for cat in disliked_categories]
            for category in liked_translated:
                query = query.filter(Boardgames.categories.like(f'%{category}%'))
            for category in disliked_translated:
                query = query.filter(~Boardgames.categories.like(f'%{category}%'))
            games = query.order_by(Boardgames.rating.desc()).limit(limit).all()
            return [self._format_db_game_to_dict(game) for game in games]
        except Exception as e:
            logger.error(f"Ошибка получения рекомендаций: {str(e)}")
            return []
        finally:
            db_sess.close()

    def get_party_games(self,
                        min_players: int = 4,
                        max_playtime: int = 60,
                        limit: int = 5) -> List[Dict]:
        """Получает игры, подходящие для вечеринок"""
        db_sess = db_session.create_session()
        try:
            games = db_sess.query(Boardgames).filter(
                Boardgames.players.contains(f"{min_players}-"),
                Boardgames.playtime.contains(str(max_playtime)),
                Boardgames.weight < 2.5,
                Boardgames.users_rated >= self.min_users_rated
            ).order_by(Boardgames.rating.desc()).limit(limit).all()
            return [self._format_db_game_to_dict(game) for game in games]
        except Exception as e:
            logger.error(f"Ошибка получения вечериночных игр: {str(e)}")
            return []
        finally:
            db_sess.close()

    def get_family_games(self,
                         max_weight: float = 2.5,
                         min_age: int = 6,
                         limit: int = 5) -> List[Dict]:
        """Получает игры, подходящие для семей"""
        db_sess = db_session.create_session()
        try:
            family_categories = [
                self.translator.translate('Детские'),
                self.translator.translate('Семейные')
            ]
            query = db_sess.query(Boardgames).filter(
                Boardgames.weight <= max_weight,
                Boardgames.users_rated >= self.min_users_rated
            )
            from sqlalchemy import or_
            query = query.filter(or_(
                *[Boardgames.categories.like(f'%{cat}%') for cat in family_categories]
            ))
            games = query.order_by(Boardgames.rating.desc()).limit(limit).all()
            return [self._format_db_game_to_dict(game) for game in games]
        except Exception as e:
            logger.error(f"Ошибка получения семейных игр: {str(e)}")
            return []
        finally:
            db_sess.close()

    def get_strategy_games(self,
                           min_weight: float = 3.0,
                           min_playtime: int = 90,
                           limit: int = 5) -> List[Dict]:
        """Получает сложные стратегические игры"""
        db_sess = db_session.create_session()
        try:
            strategy_cat = self.translator.translate('Стратегия')
            games = db_sess.query(Boardgames).filter(
                Boardgames.weight >= min_weight,
                Boardgames.playtime.contains(str(min_playtime)),
                Boardgames.categories.like(f'%{strategy_cat}%'),
                Boardgames.users_rated >= self.min_users_rated
            ).order_by(Boardgames.rating.desc()).limit(limit).all()
            return [self._format_db_game_to_dict(game) for game in games]
        except Exception as e:
            logger.error(f"Ошибка получения стратегических игр: {str(e)}")
            return []
        finally:
            db_sess.close()


# Инициализация экземпляра поисковика
finder = BoardGameFinder()


def close_session():
    """Корректное завершение работы с БД"""
    db_sess = db_session.create_session()
    try:
        db_sess.invalidate()
        logger.info("Database connection closed")
    finally:
        db_sess.close()


# Публичные API функции
def findgame(game_name: str) -> Union[Dict, List[Dict], None]:
    """Публичный интерфейс для поиска игры по названию"""
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List[Dict]]) -> str:
    """Публичный интерфейс для форматирования информации об игре"""
    return finder.get_game_info(game_data)


def random_game(min_rating: float = 0,
                min_players: Optional[int] = None,
                max_players: Optional[int] = None) -> Dict:
    """Публичный интерфейс для получения случайной игры"""
    return finder.get_random_game(min_rating, min_players, max_players)


def get_recommendations(liked_categories: List[str] = [],
                        disliked_categories: List[str] = [],
                        min_rating: float = 7.0,
                        limit: int = 5) -> List[Dict]:
    """Публичный интерфейс для получения рекомендаций"""
    return finder.get_recommendations(liked_categories, disliked_categories, min_rating, limit)


def get_party_games(min_players: int = 4,
                    max_playtime: int = 60,
                    limit: int = 5) -> List[Dict]:
    """Публичный интерфейс для получения вечериночных игр"""
    return finder.get_party_games(min_players, max_playtime, limit)


def get_family_games(max_weight: float = 2.5,
                     min_age: int = 6,
                     limit: int = 5) -> List[Dict]:
    """Публичный интерфейс для получения семейных игр"""
    return finder.get_family_games(max_weight, min_age, limit)


def get_strategy_games(min_weight: float = 3.0,
                       min_playtime: int = 90,
                       limit: int = 5) -> List[Dict]:
    """Публичный интерфейс для получения стратегических игр"""
    return finder.get_strategy_games(min_weight, min_playtime, limit)


def get_random_game_names(count: int = 3) -> List[str]:
    """Публичный интерфейс для получения случайных названий игр"""
    return finder.get_random_game_names(count)


if __name__ == '__main__':
    # Тестирование новых функций
    print("\n=== Тест фраз ожидания ===")
    for _ in range(3):
        print(get_waiting_phrase())

    print("\n=== Тест случайных названий игр ===")
    print(get_random_game_names(5))

    print("\n=== Тест завершения сессии ===")
    close_session()
    print("Сессия завершена корректно")
