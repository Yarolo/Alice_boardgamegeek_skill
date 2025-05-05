from boardgamegeek import BGGClient, BGGItemNotFoundError
import logging
from typing import Union, List, Dict, Any
from datetime import datetime
import re
import html
import os
import time
from data.boardgames import Boardgames
from data import db_session

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
        self.skipped_results = 0
        self.search_timeout = 4.5

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
        logger.info(f'db_search_results{db_search_results}')
        if db_search_results:
            if len(db_search_results) == 1 and db_search_results[0].end_of_search == True:
                return self._format_db_game_to_dict(db_search_results[0])
            if not (len(db_search_results) == 1) and any([i.end_of_search == True for i in db_search_results]):
                games = []
                for i in db_search_results:
                    games.append(self._format_db_game_to_dict(i))
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
                logger.warning(f"Ошибка при поиске игры {game_name}")

        # Поиск по частичному совпадению
        search_results = self.bgg.search(game_name)
        if not search_results:
            raise ValueError(f"Игра '{game_name}' не найдена")
        elements_counter = len(db_search_results)
        for item in search_results[
                    len(db_search_results) + self.skipped_results:]:  # Ограничиваем количество проверяемых игр
            try:
                if time.time() - start_time > self.search_timeout - 1.7:
                    break
                game = self.bgg.game(game_id=item.id)
                if game.users_commented > 0:  # Игнорируем игры без комментариев
                    formatted_game = self._format_game_data(game)
                    if elements_counter > 15 or elements_counter == len(search_results) - 1:
                        self._save_to_db(formatted_game, game_name, True)
                    else:
                        self._save_to_db(formatted_game, game_name, False)
                    elements_counter += 1

            except Exception as e:
                logger.warning(f"Ошибка при обработке игры")
                self.skipped_results += 1
        return [{}]

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
        if not games[0]:
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


finder = BoardGameFinder()


def findgame(game_name: str) -> Union[Dict, List[Dict], None]:
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List[Dict]]) -> str:
    return finder.get_game_info(game_data)


if __name__ == '__main__':

    print("=== Точный поиск ===")
    monopoly = findgame("Monopoly")
    print(game_base_info(monopoly))

    print("\n=== Частичный поиск ===")
    for i in range(23):
        card_games = findgame("nippon: zai")
        print(game_base_info(card_games))

    print("\n=== Тест кэширования ===")
    start_time = datetime.now()
    cached_result = findgame("Monopoly")
