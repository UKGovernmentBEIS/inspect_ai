import json


def get_task_details(task_name, json_file_path):
    with open(json_file_path, "r") as file:
        tasks = json.load(file)
        for task in tasks:
            if task["challenge"] == task_name:
                return task
    return None


def create_system_task_file(task_details, template_file_path, output_file_path):
    try:
        with open(template_file_path, "r") as file:
            content = file.read()
        content = content.replace("{TARGET_ADDR}", task_details["address"])
        content = content.replace("{COMMAND}", task_details["command"])
        with open(output_file_path, "w") as file:
            file.write(content)
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False
