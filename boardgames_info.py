from boardgamegeek import BGGClient, BGGItemNotFoundError
from functools import lru_cache
import logging
from typing import Union, List, Optional, Dict, Any
import json
from datetime import datetime

# Настройка продвинутого логирования
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
    """Класс для поиска и обработки информации о настольных играх."""

    def __init__(self):
        self.bgg = BGGClient(
            requests_per_minute=30,
            retries=3,
            retry_delay=5,
            timeout=30
        )
        self.cache_file = 'games_cache.json'
        self._load_cache()

    def _load_cache(self) -> None:
        """Загружает кэш из файла."""
        try:
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}

    def _save_cache(self) -> None:
        """Сохраняет кэш в файл."""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    @lru_cache(maxsize=1000)
    def find_game(self, game_name: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Ищет игру по названию с использованием кэширования и продвинутых алгоритмов поиска.

        Args:
            game_name: Название игры для поиска

        Returns:
            - Словарь с информацией об игре при точном совпадении
            - Список словарей с частичными совпадениями
        """
        game_name = game_name.strip().lower()
        if not game_name:
            raise ValueError("Название игры не может быть пустым")

        # Проверка кэша
        if game_name in self.cache:
            cached_data = self.cache[game_name]
            if datetime.now().timestamp() - cached_data['timestamp'] < 86400:  # 1 день
                return cached_data['data']

        try:
            # Попытка точного поиска
            game = self.bgg.game(game_name)
            if game and game.name.lower() == game_name:
                result = self._format_game_data(game)
                self._update_cache(game_name, result)
                return result
        except BGGItemNotFoundError:
            pass

        # Поиск по частичному совпадению
        search_results = self.bgg.search(game_name)
        if not search_results:
            raise ValueError(f"Игра '{game_name}' не найдена")

        games = []
        for item in search_results[:15]:  # Ограничиваем количество проверяемых игр
            try:
                game = self.bgg.game(game_id=item.id)
                if game.users_commented > 0:  # Игнорируем игры без комментариев
                    formatted_game = self._format_game_data(game)
                    games.append(formatted_game)

                    # Если нашли точное совпадение - возвращаем сразу
                    if game.name.lower() == game_name:
                        self._update_cache(game_name, formatted_game)
                        return formatted_game
            except Exception as e:
                logger.warning(f"Ошибка при получении игры {item.id}: {str(e)}")
                continue

        if not games:
            raise ValueError("Не найдено подходящих игр")

        # Сортируем по популярности и релевантности
        sorted_games = sorted(
            games,
            key=lambda x: (
                -x['users_commented'],
                -self._match_score(x['name'], game_name),
                -x['rating']
            )
        )

        self._update_cache(game_name, sorted_games)
        return sorted_games

    def _format_game_data(self, game) -> Dict[str, Any]:
        """Форматирует данные игры в словарь."""
        return {
            'id': game.id,
            'name': game.name,
            'year': game.year,
            'description': getattr(game, 'description', 'Описание отсутствует'),
            'players': f"{game.min_players}-{game.max_players}" if hasattr(game, 'min_players') else "N/A",
            'playtime': f"{game.playing_time} мин" if hasattr(game, 'playing_time') else "N/A",
            'rating': getattr(game, 'rating_average', 0),
            'users_commented': getattr(game, 'users_commented', 0),
            'categories': getattr(game, 'categories', []),
            'mechanics': getattr(game, 'mechanics', []),
            'thumbnail': getattr(game, 'thumbnail', None),
            'image': getattr(game, 'image', None),
            'last_updated': datetime.now().timestamp()
        }

    def _match_score(self, game_name: str, query: str) -> float:
        """Вычисляет оценку соответствия названия игры запросу."""
        game_name = game_name.lower()
        query = query.lower()

        if game_name == query:
            return 1.0

        # Проверяем содержит ли название запрос
        if query in game_name:
            return 0.9

        # Проверяем на схожесть слов
        query_words = set(query.split())
        game_words = set(game_name.split())
        common_words = query_words & game_words

        return len(common_words) / max(len(query_words), 1)

    def _update_cache(self, game_name: str, data: Any) -> None:
        """Обновляет кэш данных."""
        self.cache[game_name] = {
            'data': data,
            'timestamp': datetime.now().timestamp()
        }
        self._save_cache()

    def get_game_info(self, game_data: Union[Dict, List]) -> str:
        """
        Форматирует информацию об игре в читаемый текст.

        Args:
            game_data: Данные игры (одиночные или список)

        Returns:
            Форматированная строка с информацией
        """
        if isinstance(game_data, list):
            return self._format_multiple_games(game_data)
        return self._format_single_game(game_data)

    def _format_single_game(self, game: Dict[str, Any]) -> str:
        """Форматирует информацию об одной игре."""
        info = [
            f"🎲 {game['name']} ({game['year']})",
            f"👥 Игроков: {game['players']}",
            f"⏱ Время игры: {game['playtime']}",
            f"⭐ Рейтинг: {game['rating']:.2f}",
            f"📝 Описание: {game['description'][:300]}..." if len(game['description']) > 300 else game['description'],
            f"🏷 Категории: {', '.join(game['categories'][:5])}" if game['categories'] else "",
            f"⚙ Механики: {', '.join(game['mechanics'][:5])}" if game['mechanics'] else ""
        ]
        return '\n'.join(filter(None, info))

    def _format_multiple_games(self, games: List[Dict[str, Any]]) -> str:
        """Форматирует информацию о нескольких играх."""
        if not games:
            return "Игры не найдены"

        games_list = []
        for i, game in enumerate(games[:5], 1):  # Ограничиваем 5 играми
            games_list.append(
                f"{i}. {game['name']} ({game['year']}) - ⭐ {game['rating']:.1f} "
                f"(👥 {game['players']}, ⏱ {game['playtime']})"
            )

        return (
                "Найдено несколько игр. Уточните запрос:\n\n" +
                '\n'.join(games_list) +
                "\n\nПоказано топ-5 из найденных игр."
        )


# Интерфейсные функции для обратной совместимости
finder = BoardGameFinder()


def findgame(game_name: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """Интерфейсная функция для поиска игры (совместимость со старым кодом)."""
    return finder.find_game(game_name)


def game_base_info(game_data: Union[Dict, List]) -> str:
    """Интерфейсная функция для получения информации об игре (совместимость)."""
    return finder.get_game_info(game_data)


if __name__ == '__main__':
    # Примеры использования
    try:
        # Тестирование точного поиска
        print("=== Точный поиск ===")
        monopoly = findgame("Monopoly")
        print(game_base_info(monopoly))

        # Тестирование частичного совпадения
        print("\n=== Частичный поиск ===")
        card_games = findgame("Card")
        print(game_base_info(card_games))

        # Тестирование кэширования
        print("\n=== Тест кэширования ===")
        start_time = datetime.now()
        cached_result = findgame("Monopoly")
        print(f"Время выполнения (с кэшем): {datetime.now() - start_time}")

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")