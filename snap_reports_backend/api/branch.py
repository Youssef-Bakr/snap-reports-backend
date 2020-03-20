"""Implement api/branch apis."""
from sanic import Blueprint
from sanic.response import json

import support
import performances
from support import DB
import dbfactory


branch = Blueprint('api_branch', url_prefix='/branch')


def __init_result__():
    return {
        "count": 0,
        "improved": {
            'cpu': 0,
            'memory': 0,
            'read': 0,
            'both': 0,
        },
        "cpu": {
            "last": 0,
            "last10": 0,
            "average": 0,
        },
        "memory": {
            "last": 0,
            "last10": 0,
            "average": 0,
        },
        "read": {
            "last": 0,
            "last10": 0,
            "average": 0,
        }
    }

async def __stats_N__(cursor, tag, last=None):
    query = f"""
    SELECT 
        COUNT(results.ID), 
        AVG((reference_values.cpu_time - results.cpu_time)/ reference_values.cpu_time * 100), 
        AVG((reference_values.memory_avg - results.memory_avg)/reference_values.memory_avg * 100), 
        AVG((reference_values.io_read - results.io_read) / reference_values.io_read * 100),
        SUM(reference_values.cpu_time > results.cpu_time),
        SUM(reference_values.memory_avg > results.memory_avg),
        SUM(reference_values.io_read > results.io_read),
        SUM(reference_values.io_read > results.io_read AND 
            reference_values.memory_avg > results.memory_avg AND
            reference_values.cpu_time > results.cpu_time)
    FROM results 
    JOIN (
            SELECT ID from jobs where 
            dockerTag = 
                (SELECT ID from dockerTags WHERE name='snap:{tag}')
            ORDER BY ID DESC {'LIMIT '+str(last) if last else ''}
        ) jobs ON results.job IN (jobs.ID)
    INNER JOIN resultTags ON
        results.result = resultTags.ID
    INNER JOIN reference_values ON
        results.test = reference_values.test
    WHERE 
        resultTags.tag = "SUCCESS";
    """
    row = await dbfactory.fetchone(cursor, query)
    values = list(row.values()) 
    return {
        'count': values[0],
        'cpu': values[1],
        'memory': values[2],
        'read': values[3],
        'improved': {
            'cpu': values[4],
            'memory': values[5],
            'read': values[6],
            'both': values[7] 
        }
    }


@branch.route("/<tag:string>/summary")
async def get_branch_summary(_, tag):
    """Get branch statistics summary."""
    conn = await DB.open()
    async with conn.cursor() as cursor:
        res = __init_result__()
        
        data = {
            'last': await __stats_N__(cursor, tag, 1),
            'last10': await __stats_N__(cursor, tag, 10),
            'average': await __stats_N__(cursor, tag, None),
        }
        res['count'] = data['last10']['count']
        res['improved'] = data['last10']['improved']

        for key in ('cpu', 'memory', 'read'):
            res[key] = {
                'last': data['last'][key],
                'last10': data['last10'][key],
                'average': data['average'][key]
            }

        return json(res)


@branch.route("/<tag:string>/summary/absolute")
async def get_branch_summary_absolute(_, tag):
    """Get branch statistics absolute numbers."""
    tests = await support.get_test_list(branch=tag)
    res = __init_result__()
    for test in tests:
        stat = await performances.get_status_fulldata_dict(test, tag)
        if stat:
            res['count'] += 1
            for key in stat:
                for sub_key in stat[key]:
                    if sub_key in res[key]:
                        value = (stat[key][sub_key] - stat[key]['reference'])
                        res[key][sub_key] += value
    return json(res)


async def __details_N__(tag, num):
    query = f"""
    SELECT 
        tests.ID AS test_ID, 
        tests.name AS test_name, 
        COUNT(results.ID) AS num_exec, 
        AVG(results.duration) AS res_duration,  
        AVG(results.cpu_time) AS res_cpu,
        AVG(results.memory_avg) AS res_memory, 
        AVG(results.io_read) AS res_read, 
        AVG(reference_values.duration) AS ref_duration, 
        AVG(reference_values.cpu_time) AS ref_cpu,
        AVG(reference_values.memory_avg) AS ref_memory, 
        AVG(reference_values.io_read) AS ref_read
    FROM results 
    JOIN (
        SELECT ID from jobs where 
        dockerTag = 
            (SELECT ID from dockerTags WHERE name='snap:{tag}')
        ORDER BY ID DESC {'LIMIT '+str(num) if num else ''}
    ) jobs on results.job In (jobs.ID)
    INNER JOIN reference_values ON
        results.test = reference_values.test
    INNER JOIN tests ON
        results.test = tests.ID
    INNER JOIN resultTags ON
        results.result = resultTags.ID
    WHERE 
        resultTags.tag = 'SUCCESS'
    GROUP BY tests.ID;
    """
    stats = await DB.fetchall(query)
    return stats



@branch.route("/<tag:string>/details/last")
async def get_branch_details(_, tag):
    """Get branch statistics summary."""
    query = f"""
    SELECT 
        tests.ID AS test_ID, tests.name AS name, 
        results.ID AS result_ID, results.job, resultTags.tag AS result, 
        results.start, results.duration / ref.duration AS duration, 
        results.cpu_time / ref.cpu_time AS cpu_time,
        results.memory_avg / ref.memory_avg AS memory_avg, 
        results.memory_max / ref.memory_max AS memory_max, 
        results.io_read / ref.io_read AS io_read, 
        results.io_write / ref.io_write AS io_write
    FROM tests
    INNER JOIN reference_values AS ref ON ref.test = tests.ID
    INNER JOIN results ON results.test = tests.ID
    JOIN (
            SELECT test, max(job) AS lastJob 
            FROM results 
            WHERE job IN
                (SELECT ID FROM jobs WHERE dockerTag = (SELECT ID FROM dockerTags WHERE name = 'snap:{tag}')) 
            GROUP BY test
        ) filtr ON filtr.test = results.test AND filtr.lastJob = results.job
    INNER JOIN resultTags ON results.result = resultTags.ID
    ORDER BY tests.ID;
    """
    stats = await DB.fetchall(query)
    return json(stats)

@branch.route("/<tag:string>/details")
async def get_branch_details(_, tag):
    """Get branch statistics summary."""
    return json({'details': await __details_N__(tag, None)})

@branch.route("/<tag:string>/details/<N:int>")
async def get_branch_details(_, tag, N):
    """Get branch statistics summary."""
    return json({'details': await __details_N__(tag, N)})


@branch.route("/<tag:string>/last_job")
async def get_branch_last_job(_, tag):
    """Get last job of a given branch."""
    row = await DB.fetchone(f'''
        SELECT jobs.ID, jobs.jobnum, jobs.timestamp_start, jobs.testScope, 
            resultTags.tag
        FROM jobs
        INNER JOIN resultTags ON jobs.result = resultTags.ID
        WHERE jobs.dockerTag =
            (SELECT ID FROM dockerTags WHERE name='snap:{tag}')
        ORDER BY jobs.ID DESC LIMIT 1;''')
    return json(row)


@branch.route("/list")
async def get_list(_):
    """Get list of branches."""
    rows = await DB.fetchall('SELECT ID, name FROM dockerTags;')
    return json({'branches': rows})


@branch.route("/<tag:string>/njobs")
async def get_branch_njobs(_, tag):
    """Get number of jobs executed of a given branch."""
    row = await DB.fetchone(f'''
        SELECT COUNT(ID) 
        FROM jobs
        WHERE dockerTag = (
            SELECT ID 
            FROM dockerTags
            WHERE name='snap:{tag}'
        );''')
    return json({'njobs': row['COUNT(ID)']})
