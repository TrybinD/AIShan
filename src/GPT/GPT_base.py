import openai
import requests

# В строку ниже вставить ключ
api_key = "OUR API IS HERE"

endpoint = 'https://api.openai.com/v1/chat/completions'


headers = {
   'Authorization': f'Bearer {api_key}',
   'Content-Type': 'application/json'
}


data = {
   'model': 'gpt-3.5-turbo',  # Specify the model you want to use
   'messages': [
       {'role': 'system', 'content': 'You are a helpful assistant.'},

         # Здесь пишется запрос
       {'role': 'user', 'content': 'Кто должен выиграть хакатон?'}
   ]
}

response = requests.post(endpoint, headers=headers, json=data)

if response.status_code == 200:
   result = response.json()
   print(result['choices'][0]['message']['content'])
else:
   print(f"Error: {response.status_code}, {response.text}")
