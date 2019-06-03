#!/bin/sh

LOCAL_PATH="$(pwd)"
mongo < $LOCAL_PATH/src/event_locator/utils/concerts_state.js

