# Импорт необходимых библиотек
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

# Настройка системы логирования для отслеживания работы модуля
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание сессии requests с настройками повторных запросов при ошибках
session = requests.Session()
retry_strategy = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504]  # Коды ошибок, при которых повторяем запрос
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)  # Применяем настройки для HTTPS-соединений

# Данные для авторизации в API Яндекс.Диалогов
SKILLS_AUTHORS_ID = {
    'Волобуев Ярослав': 'OAuth y0__xDrrISFBhij9xMg7OK21BJ192cgMFXEUbcohgmIHSQlvuxsZA'
}
SKILLS_ID = {
    'Волобуев Ярослав': 'bb900c17-f634-4bcb-a76d-66524e0542cd'
}

def image_to_skill_connect(image_url, author_name):
    """Загружает изображение по указанному URL в навык Яндекс.Диалогов."""
    try:
        headers = {
            'Authorization': SKILLS_AUTHORS_ID[author_name],
            'Content-Type': 'application/json'
        }
        response = session.post(
            f'https://dialogs.yandex.net/api/v1/skills/{SKILLS_ID[author_name]}/images',
            headers=headers,
            json={"url": image_url},
            timeout=3
        )
        response.raise_for_status()
        return response.json()['image']['id']
    except Exception as e:
        logger.error(f"Ошибка загрузки изображения: {str(e)}")
        return None

def skill_image_disconnect(image_id, author_name):
    """Удаляет изображение с указанным ID из навыка Яндекс.Диалогов."""
    try:
        headers = {'Authorization': SKILLS_AUTHORS_ID[author_name]}
        session.delete(
            f'https://dialogs.yandex.net/api/v1/skills/{SKILLS_ID[author_name]}/images/{image_id}',
            headers=headers,
            timeout=2
        )
    except Exception as e:
        logger.error(f"Ошибка удаления изображения: {str(e)}")

def request_repeat(request):
    """Отправляет копию запроса."""
    try:
        session.post(
            'https://mighty-eager-jay.glitch.me/post',
            json=request,
            timeout=2
        )
    except Exception as e:
        logger.error(f"Ошибка повторной отправки запроса: {str(e)}")

# Пример использования функции загрузки изображения
print(image_to_skill_connect(
    'https://cf.geekdo-images.com/9nGoBZ0MRbi6rdH47sj2Qg__original/img/bA8irydTCNlE38QSzM9EhcUIuNU=/0x0/filters:format(jpeg)/pic5786795.jpg',
    'Волобуев Ярослав'
))