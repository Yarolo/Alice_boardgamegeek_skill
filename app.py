from waitress import serve
from flask import Flask, request, jsonify
import logging
from boardgames_info import findgame, game_base_info, get_random_game_names
from http_work import skill_image_disconnect, image_to_skill_connect
import random
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessionStorage = {}

DICE = {1: '⚀', 2: '⚁', 3: '⚂', 4: '⚃', 5: '⚄', 6: '⚅'}
# Фразы для ожидания
WAITING_PHRASES = [
    "Жду-не дождусь...",
    "Сколько ж ещё?",
    "Время бежит, ты идёшь...",
    "Как в сказке — не было ни конца, ни края у этой лужи, её орёл не перелетел...",
    "Может, чайку попьём с ватрушками?",
    "Жду как премьеры нового сезона баскетбола Куроко!",
    "Это надолго...",
    "Терпение, только терпение...",
    "Оторвать бы этим разрабам руки, глядишь с дивана встанут",
    "Так и состариться можно!",
    "Может, три раза щёлкнем?",
    "Сидим, ждём у моря погоды.",
    "Пока ждём — жизнь проходит, ба, так уже прошла, ничего потомки дождутся!",
    "Считаю до пяти!!!",
    "Как время летит быстро, даже Иван успел к проекту приступить, всего каких-то пару сотен лет прошло."
]

QUICK_RESPONSES = {
    'привет': lambda name: f'Привет, {name}! Чем могу помочь?',
    'здравствуй': lambda name: f'Здравствуй, {name}! Как я могу помочь?',
    'спасибо': 'Пожалуйста! Обращайтесь ещё!',
    'благодарю': 'Всегда рад помочь!',
    'пока': 'До свидания! Хорошего дня!',
    'до свидания': 'До свидания! Рада была помочь!',
    'до встречи': 'До свидания! Буду ждать вас снова!',
    'что ты умеешь': 'Я могу рассказать о настольных играх, бросить кубики или вытянуть карты. Что вас интересует?'
}


@app.route('/post', methods=['POST'])
def main():
    start_time = time.time()
    response = {
        'session': request.json['session'],
        'version': request.json['version'],
        'response': {
            'end_session': False
        }
    }
    handle_dialog(request.json, response)

    logger.info(f"Request processed in {time.time() - start_time:.3f}s")
    return jsonify(response)


def handle_dialog(req, res):
    user_id = req['session']['user_id']
    command = req['request']['command']

    if sessionStorage.get('image_id'):
        skill_image_disconnect(sessionStorage['image_id'], 'Волобуев Ярослав')
        sessionStorage.pop('image_id', None)

    for quick_cmd, response in QUICK_RESPONSES.items():
        if quick_cmd in command:
            if callable(response):
                res['response']['text'] = response(sessionStorage.get(user_id, {}).get('first_name', 'друг'))
            else:
                res['response']['text'] = response
            if quick_cmd == 'пока' or quick_cmd == 'до свидания' or quick_cmd == 'до встречи':
                res['response']['end_session'] = True
            return

    if req['session']['new']:
        res['response']['text'] = 'Привет! Назови свое имя!'
        sessionStorage[user_id] = {'first_name': None}
        return
    if sessionStorage[user_id]['first_name'] is None:
        acquaintance(req, res, user_id)
    else:
        if 'игр' in command and 'настольн' in command:
            res['response']['text'] = 'О какой настольной игре рассказать?'
            res['response']['buttons'] = [{'title': i, 'hide': True} for i in get_random_game_names()]
            sessionStorage['boardgames_info'] = True
            sessionStorage['dice_pull'] = False
            sessionStorage['draw_cards'] = False
        elif ('кост' in command or 'куб' in command) and 'брос' in command:
            res['response']['text'] = 'Сколько кубиков кидаем?'
            sessionStorage['draw_cards'] = False
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = True
        elif ('вытя' in command or 'результат' in command) and 'карт' in command:
            res['response']['text'] = 'Сколько карт вытягиваем?'
            sessionStorage['draw_cards'] = True
            sessionStorage['boardgames_info'] = False
            sessionStorage['dice_pull'] = False
        elif sessionStorage.get('boardgames_info'):
            boardgames_dialog(req, res)
        elif sessionStorage.get('dice_pull'):
            dice_dialog(req, res)
        elif sessionStorage.get('draw_cards'):
            draw_cards(req, res)
        else:
            res['response']['text'] = 'Не поняла ваш запрос.'


def boardgames_dialog(req, res):
    try:
        boardgames = findgame(sessionStorage.get('game_name', req['request']['original_utterance']))
    except ValueError:
        res['response']['text'] = 'Извините, не смогла найти подходящие результаты.'
        return
    res['response']['text'] = game_base_info(boardgames)
    if not isinstance(boardgames, list):
        im_id = image_to_skill_connect(boardgames['image'], 'Волобуев Ярослав')
        if im_id:
            res['response']['card'] = {
                "type": "BigImage",
                "image_id": im_id,
                "title": boardgames['name'],
                "description": game_base_info(boardgames),
            }
            sessionStorage['image_id'] = im_id
    elif not boardgames[0]:
        sessionStorage['game_name'] = sessionStorage.get('game_name', req['request']['original_utterance'])
        res['response']['buttons'] = [{'title': get_waiting_phrase(), 'hide': True}]
        return
    if sessionStorage.get('game_name'):
        del sessionStorage['game_name']


def acquaintance(req, res, user_id):
    first_name = get_first_name(req)
    if first_name is None:
        res['response']['text'] = 'Не расслышала имя. Повтори, пожалуйста!'
    else:
        sessionStorage[user_id]['first_name'] = first_name
        res['response']['text'] = f'Приятно познакомиться, {first_name.title()}! Чем помочь?'
        res['response']['buttons'] = [
            {'title': 'Информация о настольной игре', 'hide': True},
            {'title': 'Бросить кубики', 'hide': True},
            {'title': 'Вытянуть карты', 'hide': True}
        ]


def dice_dialog(req, res):
    number_dices = get_number(req)
    result = []
    if not number_dices:
        res['response']['text'] = 'Не расслышала ответ. Введите число брошенных кубиков.'
        return
    for i in range(number_dices):
        result.append(DICE[random.choice(range(1, 7))])
    result = sorted(result)
    answer = f'Ваш результат:\n{"".join(result)}'
    if number_dices == 5:
        combos = []
        for i in DICE.values():
            combos.append(result.count(i))
        if 5 in combos:
            answer += '\n Комбинация из кубиков: Покер.'
        elif 3 in combos and 2 in combos:
            answer += '\n Комбинация из кубиков: Фулхаус.'
        elif result == '⚀⚁⚂⚃' or result == '⚁⚂⚃⚄' or result == '⚂⚃⚄⚅':
            answer += '\n Комбинация из кубиков: Короткий стрит.'
        elif result == '⚁⚂⚃⚄⚅' or result == '⚀⚁⚂⚃⚄':
            answer += '\n Комбинация из кубиков: Длинный стрит.'
        elif 4 in combos:
            answer += '\n Комбинация из кубиков: Каре.'
    res['response']['text'] = answer


def draw_cards(req, res):
    CARD_SUITS = {'spades': '♠', 'hearts': '♥', 'diamonds': '♦', 'clubs': '♣'}
    CARD_VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    full_deck = [f"{value}{suit}" for suit in CARD_SUITS.values() for value in CARD_VALUES]

    num_cards = get_number(req)
    if not num_cards or num_cards < 1:
        res['response']['text'] = "Пожалуйста, укажите число от 1 до 10"
        return

    num_cards = min(num_cards, 10)
    drawn_cards = random.sample(full_deck, num_cards)
    res['response']['text'] = f"Вытянутые карты:\n {' '.join(drawn_cards)}"


def get_first_name(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.FIO':
            return entity['value'].get('first_name', None)


def get_number(req):
    for entity in req['request']['nlu']['entities']:
        if entity['type'] == 'YANDEX.NUMBER':
            return entity.get('value', None)


def get_waiting_phrase() -> str:
    """Возвращает случайную фразу ожидания"""
    return random.choice(WAITING_PHRASES)


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=5000)
