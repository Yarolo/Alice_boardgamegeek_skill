import html
import logging
import os
import re
import time
from datetime import datetime
from typing import Union, List, Dict, Any, Optional
from random import choice

from boardgamegeek import BGGClient, BGGItemNotFoundError
from googletrans import Translator

from data import db_session
from data.boardgames import Boardgames

if not os.path.exists('db'):
    os.makedirs('db')
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


class BoardGameFinder:
    def __init__(self):
        self.bgg = BGGClient(
            requests_per_minute=30,
            retries=3,
            retry_delay=5,
            timeout=30
        )
        self.translator = Translator()
        self.skipped_results = 0
        self.search_timeout = 4.5

    def _translate_text(self, text: str, src_lang: str = 'en', dest_lang: str = 'ru') -> str:
        if not text or text.strip() == 'N/A':
            return text
        try:
            translation = self.translator.translate(text, src=src_lang, dest=dest_lang)
            return translation.text
        except Exception as e:
            logger.warning(f"Ошибка перевода текста: {str(e)}")
            return text

    def _format_db_game_to_dict(self, db_game: Boardgames) -> Dict:
        return {
            'id': db_game.bgg_id,
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
        }

    def _save_to_db(self, game_data: Dict, search_query: str, end_of_search: bool):
        db_sess = db_session.create_session()
        try:
            game = Boardgames(
                bgg_id=game_data['id'],
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
                search_time=datetime.now(),
                end_of_search=end_of_search
            )
            db_sess.add(game)
            db_sess.commit()
        except Exception as e:
            logger.error(f"Error saving to database: {str(e)}")
            db_sess.rollback()
        finally:
            db_sess.close()

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

    def find_game(self, game_name: str, use_cache: bool = True) -> Union[Dict, List[Dict], str, None]:
        db_sess = db_session.create_session()
        start_time = time.time()
        game_name = game_name.strip().lower()
        if not game_name:
            raise ValueError("Название игры не может быть пустым")

        db_search_results = db_sess.query(Boardgames).filter(Boardgames.search_query == game_name).all()
        if db_search_results:
            if len(db_search_results) == 1 and db_search_results[0].end_of_search:
                return self._format_db_game_to_dict(db_search_results[0])
            if len(db_search_results) > 1 and any(i.end_of_search for i in db_search_results):
                games = [self._format_db_game_to_dict(i) for i in db_search_results]
                return sorted(
                    games,
                    key=lambda x: (
                        -x.get('users_rated', 0),
                        -self._match_score(x['name'], game_name),
                        -x.get('rating', 0)
                    )
                )
        else:
            try:
                game = self.bgg.game(game_name)
                if game and game.name.lower() == game_name:
                    result = self._format_game_data(game)
                    self._save_to_db(result, game_name, True)
                    return result
            except BGGItemNotFoundError as e:
                logger.warning(f"Ошибка при поиске игры {game_name}: {str(e)}")

        search_results = self.bgg.search(game_name)
        if not search_results:
            raise ValueError(f"Игра '{game_name}' не найдена")

        elements_counter = len(db_search_results)
        for item in search_results[len(db_search_results) + self.skipped_results:]:
            try:
                if time.time() - start_time > self.search_timeout - 0.5:
                    break
                game = self.bgg.game(game_id=item.id)
                if game.users_commented > 0:
                    formatted_game = self._format_game_data(game)
                    if elements_counter > 15:
                        self._save_to_db(formatted_game, game_name, True)
                    else:
                        self._save_to_db(formatted_game, game_name, False)
                    elements_counter += 1
            except Exception as e:
                logger.warning(f"Ошибка при обработке игры {item.id}: {str(e)}")
                self.skipped_results += 1
        return [{}]

    def _format_game_data(self, game) -> Dict:
        game_data = {
            'id': game.id,
            'name': game.name,
            'year': game.year,
            'description': self._format_description(
                self._translate_text(getattr(game, 'description', 'Описание отсутствует'))
            ),
            'players': f"{game.min_players}-{game.max_players}" if hasattr(game, 'min_players') else "N/A",
            'playtime': f"{game.playing_time} мин" if hasattr(game, 'playing_time') else "N/A",
            'rating': round(getattr(game, 'rating_average', 0), 2),
            'weight': round(getattr(game, 'rating_average_weight', 0), 2),
            'users_rated': getattr(game, 'users_rated', 0),
            'thumbnail': getattr(game, 'thumbnail', None),
            'image': getattr(game, 'image', None),
        }

        categories = getattr(game, 'categories', [])
        mechanics = getattr(game, 'mechanics', [])

        game_data['categories'] = [self._translate_text(cat) for cat in categories]
        game_data['mechanics'] = [self._translate_text(mec) for mec in mechanics]

        return game_data

    def _match_score(self, game_name: str, query: str) -> float:
        game_name = game_name.lower()
        query = query.lower()
        if game_name == query:
            return 1.0
        if query in game_name:
            return 0.9
        query_words = set(query.split())
        game_words = set(game_name.split())
        return len(query_words & game_words) / max(len(query_words), 1)

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
            f"🏷 Категории: {', '.join(game['categories'][:5])}" if game.get('categories') else "",
            f"⚙ Механики: {', '.join(game['mechanics'][:5])}" if game.get('mechanics') else ""
        ]
        return '\n'.join(filter(None, info))

    def _format_multiple_games(self, games: List[Dict[str, Any]]) -> str:
        if not games or not games[0]:
            return "Поиск продолжается"

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

    # 1. Получение случайной игры с фильтрацией по параметрам
    def get_random_game(self,
                        min_rating: float = 0,
                        min_players: Optional[int] = None,
                        max_players: Optional[int] = None) -> Dict:
        db_sess = db_session.create_session()
        try:
            query = db_sess.query(Boardgames).filter(Boardgames.rating >= min_rating)

            if min_players is not None:
                query = query.filter(Boardgames.players.contains(f"{min_players}-"))
            if max_players is not None:
                query = query.filter(Boardgames.players.contains(f"-{max_players}"))

            games = query.all()
            if games:
                return self._format_db_game_to_dict(choice(games))
            return {}
        finally:
            db_sess.close()

    # 2. Получение рекомендаций на основе предпочтений
    def get_recommendations(self,
                            liked_categories: List[str] = [],
                            disliked_categories: List[str] = [],
                            min_rating: float = 7.0,
                            limit: int = 5) -> List[Dict]:
        db_sess = db_session.create_session()
        try:
            query = db_sess.query(Boardgames).filter(Boardgames.rating >= min_rating)

            for category in liked_categories:
                query = query.filter(Boardgames.categories.like(f'%{category}%'))

            for category in disliked_categories:
                query = query.filter(~Boardgames.categories.like(f'%{category}%'))

            games = query.order_by(Boardgames.rating.desc()).limit(limit).all()
            return [self._format_db_game_to_dict(game) for game in games]
        finally:
            db_sess.close()

    # 3. Поиск игр для вечеринки (быстрые и простые игры для компании)
    def get_party_games(self,
                        min_players: int = 4,
                        max_playtime: int = 60,
                        limit: int = 5) -> List[Dict]:
        db_sess = db_session.create_session()
        try:
            games = db_sess.query(Boardgames).filter(
                Boardgames.players.contains(f"{min_players}-"),
                Boardgames.playtime.contains(str(max_playtime)),
                Boardgames.weight < 2.5
            ).order_by(Boardgames.rating.desc()).limit(limit).all()

            return [self._format_db_game_to_dict(game) for game in games]
        finally:
            db_sess.close()

    # 4. Поиск семейных игр (для детей и взрослых)
    def get_family_games(self,
                         max_weight: float = 2.5,
                         min_age: int = 6,
                         limit: int = 5) -> List[Dict]:
        db_sess = db_session.create_session()
        try:
            games = db_sess.query(Boardgames).filter(
                Boardgames.weight <= max_weight,
                Boardgames.categories.like('%Детская%') |
                Boardgames.categories.like('%Семейная%')
            ).order_by(Boardgames.rating.desc()).limit(limit).all()

            return [self._format_db_game_to_dict(game) for game in games]
        finally:
            db_sess.close()

    # 5. Поиск стратегических игр (сложные и долгие игры)
    def get_strategy_games(self,
                           min_weight: float = 3.0,
                           min_playtime: int = 90,
                           limit: int = 5) -> List[Dict]:
        db_sess = db_session.create_session()
        try:
            games = db_sess.query(Boardgames).filter(
                Boardgames.weight >= min_weight,
                Boardgames.playtime.contains(str(min_playtime)),
                Boardgames.categories.like('%Стратегия%')
            ).order_by(Boardgames.rating.desc()).limit(limit).all()

            return [self._format_db_game_to_dict(game) for game in games]
        finally:
            db_sess.close()


finder = BoardGameFinder()


def findgame(game_name: str) -> Union[Dict, List[Dict], None]:
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List[Dict]]) -> str:
    return finder.get_game_info(game_data)


def random_game(min_rating: float = 0,
                min_players: Optional[int] = None,
                max_players: Optional[int] = None) -> Dict:
    return finder.get_random_game(min_rating, min_players, max_players)


def get_recommendations(liked_categories: List[str] = [],
                        disliked_categories: List[str] = [],
                        min_rating: float = 7.0,
                        limit: int = 5) -> List[Dict]:
    return finder.get_recommendations(liked_categories, disliked_categories, min_rating, limit)


def get_party_games(min_players: int = 4,
                    max_playtime: int = 60,
                    limit: int = 5) -> List[Dict]:
    return finder.get_party_games(min_players, max_playtime, limit)


def get_family_games(max_weight: float = 2.5,
                     min_age: int = 6,
                     limit: int = 5) -> List[Dict]:
    return finder.get_family_games(max_weight, min_age, limit)


def get_strategy_games(min_weight: float = 3.0,
                       min_playtime: int = 90,
                       limit: int = 5) -> List[Dict]:
    return finder.get_strategy_games(min_weight, min_playtime, limit)


if __name__ == '__main__':
    print("=== Тест новых функций ===")
    print("\n1. Случайная игра с рейтингом >7:")
    print(game_base_info(random_game(min_rating=7)))
    print("\n2. Рекомендации для любителей стратегий:")
    recs = get_recommendations(liked_categories=['Стратегия'])
    print(game_base_info(recs))
    print("\n3. Игры для вечеринки (4+ игроков, до 60 минут):")
    party = get_party_games()
    print(game_base_info(party))
    print("\n4. Семейные игры:")
    family = get_family_games()
    print(game_base_info(family))
    print("\n5. Сложные стратегические игры:")
    strategy = get_strategy_games()
    print(game_base_info(strategy))