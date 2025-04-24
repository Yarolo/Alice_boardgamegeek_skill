import requests

SKILLS_AUTHORS_ID = {
    'Волобуев Ярослав': 'OAuth y0__xDrrISFBhij9xMg7OK21BJ192cgMFXEUbcohgmIHSQlvuxsZA'
}
SKILLS_ID = {
    'Волобуев Ярослав': 'bb900c17-f634-4bcb-a76d-66524e0542cd'
}


def image_to_skill_connect(image_url, author_name):
    headers = {
        'Authorization': SKILLS_AUTHORS_ID[author_name],
        'Content-Type': 'application/json'

    }
    response = requests.post(f'https://dialogs.yandex.net/api/v1/skills/{SKILLS_ID[author_name]}/images',
                             headers=headers,
                             json={"url": image_url}).json()
    return response['image']['id']


def skill_image_disconnect(image_id, author_name):
    headers = {'Authorization': SKILLS_AUTHORS_ID[author_name]}
    requests.delete(f'https://dialogs.yandex.net/api/v1/skills/{SKILLS_ID[author_name]}/images/{image_id}',
                    headers=headers)
