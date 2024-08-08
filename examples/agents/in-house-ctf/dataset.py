import json


def get_task_details(task_name, challenges_path, task_info_path):
    try:
        with open(challenges_path, "r") as file:
            tasks = json.load(file)
            task_info = tasks.get(task_name)
            if task_info:
                command = task_info["command"]
                prompt = task_info["prompt"]
                flag = task_info["flag"]
            else:
                print("Task {task_name} information does not exist.")
    except Exception as e:
        print(f"Error: {e}")

    try:
        with open(task_info_path, "r") as file:
            info = json.load(file)
            address = info.get("address")
    except Exception as e:
        print(f"Error: {e}")

    return command, prompt, flag, address


def create_system_message_file(command, address, template_file_path, output_file_path):
    try:
        with open(template_file_path, "r") as file:
            content = file.read()
        content = content.replace("{TARGET_ADDR}", address)
        content = content.replace("{COMMAND}", command)
        with open(output_file_path, "w") as file:
            file.write(content)
    except Exception as e:
        print(f"Error: {e}")
