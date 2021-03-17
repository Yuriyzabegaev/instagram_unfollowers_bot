FROM python:3.9

COPY main.py /
COPY instagram_unfollower /instagram_unfollower
COPY requirements.txt /
COPY locale /locale

RUN pip install -r requirements.txt
CMD [ "python", "./main.py" ]